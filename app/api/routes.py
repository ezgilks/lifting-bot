"""Dashboard REST endpoints. All of them require a magic-link bearer token."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.progression import analyze_trend, detect_stall, next_target
from app.analytics.strength import top_set
from app.analytics.volume import (
    GroupedSet,
    current_streak,
    hard_sets_for_week,
    iso_week_key,
    latest_bodyweight,
    total_hard_sets,
    week_start,
)
from app.api.auth import CurrentUser
from app.db import get_db
from app.models import ParseMethod, User
from app.parsing.pipeline import PARSER_COUNTERS
from app.queries import (
    SetRow,
    build_session_points,
    build_session_sets,
    delete_set,
    fetch_bodyweights,
    fetch_set_rows,
    get_exercise,
    get_owned_set,
    get_owned_workout,
    group_by_workout,
    parse_method_counts,
    update_set,
)
from app.queries import delete_workout as delete_workout_row
from app.schemas import (
    BodyweightPoint,
    ExerciseDetailResponse,
    ExerciseSummary,
    MuscleGroupSets,
    NextTargetResponse,
    OverviewResponse,
    ParserStatsResponse,
    SeriesPoint,
    SessionDetail,
    SetDetail,
    SetUpdate,
    StalledExercise,
    TrendInfo,
    WeekPoint,
)

router = APIRouter(prefix="/api")

TREND_WEEKS = 12
Session = Annotated[AsyncSession, Depends(get_db)]


# --------------------------------------------------------------------------
# reads
# --------------------------------------------------------------------------


@router.get("/overview", response_model=OverviewResponse)
async def overview(user: CurrentUser, session: Session) -> OverviewResponse:
    today = user.today()
    rows = await fetch_set_rows(session, user.id)
    bodyweights = await fetch_bodyweights(session, user.id)

    this_week = [r for r in rows if _same_week(r.performed_on, today)]
    last_week = [r for r in rows if _same_week(r.performed_on, today - timedelta(days=7))]
    hard = hard_sets_for_week(_grouped(this_week), today)
    bodyweight = latest_bodyweight(bodyweights, user.unit)

    return OverviewResponse(
        unit=user.unit,
        sessions_this_week=len({r.workout_id for r in this_week}),
        hard_sets_this_week=[
            MuscleGroupSets(muscle_group=group, hard_sets=count)
            for group, count in sorted(hard.items(), key=lambda kv: (-kv[1], kv[0].value))
        ],
        total_hard_sets_this_week=total_hard_sets(_grouped(this_week)),
        total_hard_sets_last_week=total_hard_sets(_grouped(last_week)),
        weekly_hard_sets=_weekly_series(rows, today),
        current_streak_days=current_streak([r.performed_on for r in rows], today),
        stalled=_stalled_exercises(rows, user),
        bodyweight=(
            None
            if bodyweight is None
            else BodyweightPoint(
                weight=bodyweight[0], unit=user.unit, recorded_on=bodyweight[1]
            )
        ),
    )


@router.get("/exercises", response_model=list[ExerciseSummary])
async def exercises(user: CurrentUser, session: Session) -> list[ExerciseSummary]:
    rows = await fetch_set_rows(session, user.id)
    by_exercise = _by_exercise(rows)

    summaries = [
        ExerciseSummary(
            id=exercise_id,
            name=items[-1].exercise_name,
            muscle_group=items[-1].muscle_group,
            equipment=items[-1].equipment,
            session_count=len({r.workout_id for r in items}),
            hard_sets=sum(1 for r in items if not r.is_warmup),
            last_trained_on=max(r.performed_on for r in items),
            top_weight=_top_weight(items, user),
        )
        for exercise_id, items in by_exercise.items()
    ]
    summaries.sort(key=lambda s: (s.last_trained_on or date.min, s.session_count), reverse=True)
    return summaries


@router.get("/exercises/{exercise_id}", response_model=ExerciseDetailResponse)
async def exercise_detail(
    exercise_id: int, user: CurrentUser, session: Session
) -> ExerciseDetailResponse:
    exercise = await get_exercise(session, exercise_id)
    if exercise is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown exercise")

    rows = await fetch_set_rows(session, user.id, exercise_id=exercise_id)
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No sets logged for this exercise")

    today = user.today()
    points = build_session_points(rows, user.unit)
    fit = analyze_trend(points, today)
    stalled = detect_stall(points, today)

    sessions: list[SessionDetail] = []
    series: list[SeriesPoint] = []
    for workout_id, performed_on, items in group_by_workout(rows):
        best = top_set([r.to_record() for r in items], user.unit)
        sessions.append(
            SessionDetail(
                workout_id=workout_id,
                performed_on=performed_on,
                sets=[
                    SetDetail(
                        set_id=r.set_id,
                        set_index=r.set_index,
                        reps=r.reps,
                        weight=r.weight,
                        unit=r.unit,
                        rpe=r.rpe,
                        is_warmup=r.is_warmup,
                    )
                    for r in items
                ],
                hard_sets=sum(1 for r in items if not r.is_warmup),
                top_weight=None if best is None else best.weight,
                top_reps=None if best is None else best.reps,
            )
        )
        if best is not None and best.weight is not None:
            series.append(
                SeriesPoint(performed_on=performed_on, value=best.weight, reps=best.reps)
            )

    target = next_target(
        build_session_sets(rows, user.unit),
        user.unit,
        exercise.equipment,
        exercise.muscle_group,
        is_stalled=stalled,
    )

    return ExerciseDetailResponse(
        id=exercise.id,
        name=exercise.canonical_name,
        muscle_group=exercise.muscle_group,
        equipment=exercise.equipment,
        unit=user.unit,
        sessions=sessions,
        top_weight_series=series,
        trend=TrendInfo(
            slope_per_week=fit.slope_per_week if fit else None,
            intercept=fit.intercept if fit else None,
            sessions=len(points),
            is_stalled=stalled,
            first_session_on=fit.first_session_on if fit else None,
        ),
        next_target=(
            None
            if target is None
            else NextTargetResponse(
                kind=target.kind,
                weight=target.weight,
                unit=target.unit,
                target_reps=target.target_reps,
                sets=target.sets,
                reason=target.reason,
            )
        ),
    )


@router.get("/stats/parser", response_model=ParserStatsResponse)
async def parser_stats(user: CurrentUser, session: Session) -> ParserStatsResponse:
    counts = await parse_method_counts(session)
    rules = counts.get(ParseMethod.rules, 0)
    llm = counts.get(ParseMethod.llm, 0)
    total = rules + llm
    return ParserStatsResponse(
        rules_hits=rules,
        llm_hits=llm,
        rules_share=round(rules / total, 4) if total else 0.0,
        process_rules_hits=PARSER_COUNTERS["rules"],
        process_llm_hits=PARSER_COUNTERS["llm"],
        process_llm_failures=PARSER_COUNTERS["llm_failures"],
    )


# --------------------------------------------------------------------------
# writes -- every one re-checks ownership against the token's user
# --------------------------------------------------------------------------


@router.patch("/sets/{set_id}", response_model=SetDetail)
async def edit_set(
    set_id: int, payload: SetUpdate, user: CurrentUser, session: Session
) -> SetDetail:
    entry = await get_owned_set(session, user.id, set_id)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown set")

    updated = await update_set(
        session,
        entry,
        reps=payload.reps,
        weight=payload.weight,
        clear_weight=payload.clear_weight,
        rpe=payload.rpe,
        clear_rpe=payload.clear_rpe,
        is_warmup=payload.is_warmup,
    )
    return SetDetail(
        set_id=updated.id,
        set_index=updated.set_index,
        reps=updated.reps,
        weight=None if updated.weight is None else float(updated.weight),
        unit=updated.unit,
        rpe=None if updated.rpe is None else float(updated.rpe),
        is_warmup=updated.is_warmup,
    )


@router.delete("/sets/{set_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_set(set_id: int, user: CurrentUser, session: Session) -> Response:
    entry = await get_owned_set(session, user.id, set_id)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown set")
    await delete_set(session, entry)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/workouts/{workout_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_workout(workout_id: int, user: CurrentUser, session: Session) -> Response:
    workout = await get_owned_workout(session, user.id, workout_id)
    if workout is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown workout")
    await delete_workout_row(session, workout.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _same_week(day: date, reference: date) -> bool:
    return day.isocalendar()[:2] == reference.isocalendar()[:2]


def _grouped(rows: list[SetRow]) -> list[GroupedSet]:
    return [GroupedSet(r.performed_on, r.muscle_group, r.is_warmup) for r in rows]


def _by_exercise(rows: list[SetRow]) -> dict[int, list[SetRow]]:
    grouped: dict[int, list[SetRow]] = {}
    for row in rows:
        grouped.setdefault(row.exercise_id, []).append(row)
    return grouped


def _top_weight(rows: list[SetRow], user: User) -> float | None:
    best = top_set([r.to_record() for r in rows], user.unit)
    return None if best is None else best.weight


def _weekly_series(rows: list[SetRow], today: date) -> list[WeekPoint]:
    weeks = [
        week_start(today) - timedelta(weeks=offset)
        for offset in range(TREND_WEEKS - 1, -1, -1)
    ]
    by_week: dict[str, list[SetRow]] = {}
    for row in rows:
        by_week.setdefault(iso_week_key(row.performed_on), []).append(row)

    series: list[WeekPoint] = []
    for start in weeks:
        key = iso_week_key(start)
        items = by_week.get(key, [])
        hard = hard_sets_for_week(_grouped(items), start)
        series.append(
            WeekPoint(
                iso_week=key,
                week_start=start,
                sessions=len({r.workout_id for r in items}),
                hard_sets=dict(hard),
                total_hard_sets=sum(hard.values()),
            )
        )
    return series


def _stalled_exercises(rows: list[SetRow], user: User) -> list[StalledExercise]:
    today = user.today()
    stalled: list[StalledExercise] = []
    for exercise_id, items in _by_exercise(rows).items():
        points = build_session_points(items, user.unit)
        if not detect_stall(points, today):
            continue
        fit = analyze_trend(points, today)
        stalled.append(
            StalledExercise(
                exercise_id=exercise_id,
                name=items[-1].exercise_name,
                slope_per_week=fit.slope_per_week if fit else 0.0,
                sessions=len(points),
            )
        )
    stalled.sort(key=lambda s: s.slope_per_week)
    return stalled
