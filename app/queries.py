"""Data access shared by the bot handlers and the dashboard API.

Everything above this layer works on plain dataclasses, so the analytics
functions stay pure and testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import delete, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.progression import SessionPoint, SessionSets
from app.analytics.strength import SetRecord, set_weight_in, top_set_weight
from app.analytics.volume import BodyweightRecord
from app.models import (
    BodyweightEntry,
    Equipment,
    Exercise,
    MuscleGroup,
    ParseMethod,
    SetEntry,
    Unit,
    User,
    Workout,
)
from app.parsing.pipeline import load_catalog
from app.parsing.resolver import resolve_exercise
from app.schemas import ParsedSet


@dataclass(frozen=True)
class SetRow:
    """A denormalized set, joined to its workout and exercise."""

    set_id: int
    workout_id: int
    performed_on: date
    exercise_id: int
    exercise_name: str
    muscle_group: MuscleGroup
    equipment: Equipment
    set_index: int
    reps: int
    weight: float | None
    unit: Unit
    rpe: float | None
    is_warmup: bool

    def to_record(self) -> SetRecord:
        return SetRecord(
            performed_on=self.performed_on,
            reps=self.reps,
            weight=self.weight,
            unit=self.unit,
            is_warmup=self.is_warmup,
            workout_id=self.workout_id,
        )


def _f(value: Decimal | float | None) -> float | None:
    return None if value is None else float(value)


def group_by_workout(rows: list[SetRow]) -> list[tuple[int, date, list[SetRow]]]:
    """Rows bucketed into sessions, oldest first."""
    buckets: dict[int, list[SetRow]] = {}
    for row in rows:
        buckets.setdefault(row.workout_id, []).append(row)
    sessions = [(wid, items[0].performed_on, items) for wid, items in buckets.items()]
    sessions.sort(key=lambda s: (s[1], s[0]))
    return sessions


def build_session_points(rows: list[SetRow], unit: Unit) -> list[SessionPoint]:
    """Heaviest working set per session, for trend fitting.

    Bodyweight-only sessions carry no weight to trend, so they are skipped.
    """
    points: list[SessionPoint] = []
    for _, performed_on, items in group_by_workout(rows):
        weight = top_set_weight([r.to_record() for r in items], unit)
        if weight is not None:
            points.append(SessionPoint(performed_on=performed_on, top_weight=weight))
    return points


def build_session_sets(rows: list[SetRow], unit: Unit) -> list[SessionSets]:
    """Working sets per session as (reps, weight) pairs, normalized to ``unit``."""
    sessions: list[SessionSets] = []
    for _, performed_on, items in group_by_workout(rows):
        pairs = tuple(
            (row.reps, set_weight_in(row.to_record(), unit))
            for row in items
            if not row.is_warmup
        )
        if pairs:
            sessions.append(SessionSets(performed_on=performed_on, sets=pairs))
    return sessions


async def get_or_create_user(
    session: AsyncSession, chat_id: int, display_name: str | None
) -> tuple[User, bool]:
    """Returns the user and whether it was just created."""
    user = await session.scalar(select(User).where(User.telegram_chat_id == chat_id))
    if user is not None:
        return user, False
    user = User(telegram_chat_id=chat_id, display_name=display_name)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user, True


async def get_user(session: AsyncSession, chat_id: int) -> User | None:
    return await session.scalar(select(User).where(User.telegram_chat_id == chat_id))


async def get_user_by_id(session: AsyncSession, user_id: int) -> User | None:
    return await session.get(User, user_id)


async def fetch_set_rows(
    session: AsyncSession,
    user_id: int,
    *,
    exercise_id: int | None = None,
    since: date | None = None,
) -> list[SetRow]:
    stmt = (
        select(
            SetEntry.id,
            SetEntry.workout_id,
            Workout.performed_on,
            Exercise.id,
            Exercise.canonical_name,
            Exercise.muscle_group,
            Exercise.equipment,
            SetEntry.set_index,
            SetEntry.reps,
            SetEntry.weight,
            SetEntry.unit,
            SetEntry.rpe,
            SetEntry.is_warmup,
        )
        .join(Workout, SetEntry.workout_id == Workout.id)
        .join(Exercise, SetEntry.exercise_id == Exercise.id)
        .where(Workout.user_id == user_id)
        .order_by(Workout.performed_on, SetEntry.workout_id, SetEntry.id)
    )
    if exercise_id is not None:
        stmt = stmt.where(SetEntry.exercise_id == exercise_id)
    if since is not None:
        stmt = stmt.where(Workout.performed_on >= since)

    result = await session.execute(stmt)
    return [
        SetRow(
            set_id=row[0],
            workout_id=row[1],
            performed_on=row[2],
            exercise_id=row[3],
            exercise_name=row[4],
            muscle_group=row[5],
            equipment=row[6],
            set_index=row[7],
            reps=row[8],
            weight=_f(row[9]),
            unit=row[10],
            rpe=_f(row[11]),
            is_warmup=row[12],
        )
        for row in result.all()
    ]


async def fetch_bodyweights(session: AsyncSession, user_id: int) -> list[BodyweightRecord]:
    rows = await session.execute(
        select(BodyweightEntry.recorded_on, BodyweightEntry.weight, BodyweightEntry.unit)
        .where(BodyweightEntry.user_id == user_id)
        .order_by(desc(BodyweightEntry.recorded_on))
    )
    return [
        BodyweightRecord(recorded_on=row[0], weight=float(row[1]), unit=row[2])
        for row in rows.all()
    ]


async def save_workout(
    session: AsyncSession,
    user: User,
    performed_on: date,
    source_message: str,
    parse_method: ParseMethod,
    entries: list[tuple[int, list[ParsedSet]]],
) -> Workout:
    """Persist one workout. ``entries`` is (exercise_id, sets) in message order."""
    workout = Workout(
        user_id=user.id,
        performed_on=performed_on,
        source_message=source_message[:4000],
        parse_method=parse_method,
    )
    session.add(workout)
    await session.flush()

    for exercise_id, sets in entries:
        for index, parsed in enumerate(sets, start=1):
            session.add(
                SetEntry(
                    workout_id=workout.id,
                    exercise_id=exercise_id,
                    set_index=index,
                    reps=parsed.reps,
                    weight=None if parsed.weight is None else Decimal(str(parsed.weight)),
                    unit=parsed.unit,
                    rpe=None if parsed.rpe is None else Decimal(str(parsed.rpe)),
                    is_warmup=parsed.is_warmup,
                )
            )
    await session.commit()
    await session.refresh(workout)
    return workout


async def recent_workouts(
    session: AsyncSession, user_id: int, limit: int = 5
) -> list[Workout]:
    """Most recently created workouts first, for the undo picker."""
    rows = await session.scalars(
        select(Workout)
        .where(Workout.user_id == user_id)
        .order_by(desc(Workout.created_at), desc(Workout.id))
        .limit(limit)
    )
    return list(rows)


async def get_owned_workout(
    session: AsyncSession, user_id: int, workout_id: int
) -> Workout | None:
    """A workout, but only if this user owns it. Never trust a client id."""
    return await session.scalar(
        select(Workout).where(Workout.id == workout_id, Workout.user_id == user_id)
    )


async def get_owned_set(
    session: AsyncSession, user_id: int, set_id: int
) -> SetEntry | None:
    """A set, but only if it belongs to one of this user's workouts."""
    return await session.scalar(
        select(SetEntry)
        .join(Workout, SetEntry.workout_id == Workout.id)
        .where(SetEntry.id == set_id, Workout.user_id == user_id)
    )


async def update_set(
    session: AsyncSession,
    entry: SetEntry,
    *,
    reps: int | None = None,
    weight: float | None = None,
    clear_weight: bool = False,
    rpe: float | None = None,
    clear_rpe: bool = False,
    is_warmup: bool | None = None,
) -> SetEntry:
    """Apply a partial edit to one set.

    ``clear_weight`` / ``clear_rpe`` distinguish "set this to null" from
    "leave it alone", which a bare ``None`` cannot express.
    """
    if reps is not None:
        entry.reps = reps
    if clear_weight:
        entry.weight = None
    elif weight is not None:
        entry.weight = Decimal(str(weight))
    if clear_rpe:
        entry.rpe = None
    elif rpe is not None:
        entry.rpe = Decimal(str(rpe))
    if is_warmup is not None:
        entry.is_warmup = is_warmup

    await session.commit()
    await session.refresh(entry)
    return entry


async def delete_set(session: AsyncSession, entry: SetEntry) -> bool:
    """Delete one set, and its workout if that emptied it.

    Returns True when the parent workout was removed too.
    """
    workout_id = entry.workout_id
    await session.delete(entry)
    await session.flush()

    remaining = await session.scalar(
        select(func.count()).select_from(SetEntry).where(SetEntry.workout_id == workout_id)
    )
    if not remaining:
        await session.execute(delete(Workout).where(Workout.id == workout_id))
        await session.commit()
        return True

    await _renumber_sets(session, workout_id)
    await session.commit()
    return False


async def _renumber_sets(session: AsyncSession, workout_id: int) -> None:
    """Keep set_index contiguous and 1-based after a deletion."""
    rows = await session.scalars(
        select(SetEntry)
        .where(SetEntry.workout_id == workout_id)
        .order_by(SetEntry.exercise_id, SetEntry.id)
    )
    per_exercise: dict[int, int] = {}
    for entry in rows:
        per_exercise[entry.exercise_id] = per_exercise.get(entry.exercise_id, 0) + 1
        entry.set_index = per_exercise[entry.exercise_id]


async def latest_workout(session: AsyncSession, user_id: int) -> Workout | None:
    return await session.scalar(
        select(Workout)
        .where(Workout.user_id == user_id)
        .order_by(desc(Workout.created_at), desc(Workout.id))
        .limit(1)
    )


async def delete_workout(session: AsyncSession, workout_id: int) -> None:
    await session.execute(delete(Workout).where(Workout.id == workout_id))
    await session.commit()


async def log_bodyweight(
    session: AsyncSession, user_id: int, weight: float, unit: Unit, on: date
) -> BodyweightEntry:
    entry = BodyweightEntry(
        user_id=user_id, recorded_on=on, weight=Decimal(str(weight)), unit=unit
    )
    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    return entry


async def get_exercise(session: AsyncSession, exercise_id: int) -> Exercise | None:
    return await session.get(Exercise, exercise_id)


async def find_exercise_by_name(
    session: AsyncSession, user_id: int, text: str
) -> Exercise | None:
    """Best-effort lookup for command arguments like ``/pr bench``."""
    catalog = await load_catalog(session, user_id)
    resolution = resolve_exercise(text, catalog)
    if resolution.exercise is None:
        return None
    return await session.get(Exercise, resolution.exercise.id)


async def create_custom_exercise(
    session: AsyncSession, user_id: int, name: str, muscle_group: MuscleGroup
) -> Exercise:
    exercise = Exercise(
        canonical_name=name.strip()[:120].title(),
        aliases=[name.strip().lower()],
        muscle_group=muscle_group,
        equipment=Equipment.other,
        is_custom=True,
        owner_user_id=user_id,
    )
    session.add(exercise)
    await session.commit()
    await session.refresh(exercise)
    return exercise


async def parse_method_counts(session: AsyncSession) -> dict[ParseMethod, int]:
    rows = await session.execute(
        select(Workout.parse_method, func.count()).group_by(Workout.parse_method)
    )
    return {method: count for method, count in rows.all()}
