"""Trend fitting, stall detection, and next-session targets. Pure functions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from app.models import Equipment, MuscleGroup, Unit

TREND_WINDOW_DAYS = 8 * 7
MIN_TREND_SESSIONS = 4
STALL_WINDOW_DAYS = 3 * 7
MIN_STALL_SESSIONS = 3
DELOAD_FRACTION = 0.10

LOWER_BODY = {MuscleGroup.quads, MuscleGroup.hamstrings, MuscleGroup.glutes}
INCREMENTS: dict[Unit, tuple[float, float]] = {
    # unit -> (barbell lower body, everything else)
    Unit.lb: (5.0, 2.5),
    Unit.kg: (2.5, 1.25),
}


@dataclass(frozen=True)
class SessionPoint:
    """The heaviest working set a user hit for one exercise in one session."""

    performed_on: date
    top_weight: float


@dataclass(frozen=True)
class TrendFit:
    slope_per_week: float
    intercept: float
    sessions: int
    first_session_on: date


@dataclass(frozen=True)
class SessionSets:
    """Working sets of one session for one exercise, in performed order."""

    performed_on: date
    sets: tuple[tuple[int, float | None], ...]  # (reps, weight)


@dataclass(frozen=True)
class NextTarget:
    kind: str  # "increase" | "repeat" | "deload"
    weight: float | None
    unit: Unit
    target_reps: int
    sets: int
    reason: str


def fit_trend(points: list[SessionPoint]) -> TrendFit | None:
    """Ordinary least squares of top-set weight against days since the first session.

    Slope is reported per week. Needs at least two sessions on distinct days.
    """
    if len(points) < 2:
        return None
    ordered = sorted(points, key=lambda p: p.performed_on)
    origin = ordered[0].performed_on
    xs = [float((p.performed_on - origin).days) for p in ordered]
    ys = [p.top_weight for p in ordered]

    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    denominator = sum((x - mean_x) ** 2 for x in xs)
    if denominator == 0:
        return None
    slope_per_day = sum(
        (x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)
    ) / denominator
    intercept = mean_y - slope_per_day * mean_x
    return TrendFit(
        slope_per_week=round(slope_per_day * 7, 4),
        intercept=round(intercept, 4),
        sessions=n,
        first_session_on=origin,
    )


def _within(points: list[SessionPoint], today: date, days: int) -> list[SessionPoint]:
    cutoff = today - timedelta(days=days)
    return [p for p in points if p.performed_on >= cutoff]


def analyze_trend(points: list[SessionPoint], today: date) -> TrendFit | None:
    """Trend over the trailing 8 weeks, for exercises with enough sessions."""
    window = _within(points, today, TREND_WINDOW_DAYS)
    if len(window) < MIN_TREND_SESSIONS:
        return None
    return fit_trend(window)


def detect_stall(points: list[SessionPoint], today: date) -> bool:
    """Flat or falling top-set weight over the trailing 3 weeks, with enough sessions."""
    window = _within(points, today, STALL_WINDOW_DAYS)
    if len(window) < MIN_STALL_SESSIONS:
        return False
    fit = fit_trend(window)
    if fit is None:
        return False
    return fit.slope_per_week <= 0


def infer_rep_range(sessions: list[SessionSets], lookback: int = 4) -> tuple[int, int] | None:
    """Rep range the user has been working in, from their last few sessions."""
    recent = sorted(sessions, key=lambda s: s.performed_on)[-lookback:]
    reps = [reps for session in recent for reps, _ in session.sets]
    if not reps:
        return None
    return min(reps), max(reps)


def next_target(
    sessions: list[SessionSets],
    unit: Unit,
    equipment: Equipment,
    muscle_group: MuscleGroup,
    is_stalled: bool = False,
) -> NextTarget | None:
    """Double progression: add reps inside the range, then add weight.

    A stalled exercise gets a deload instead, regardless of the last session.
    """
    ordered = [s for s in sorted(sessions, key=lambda s: s.performed_on) if s.sets]
    if not ordered:
        return None

    rep_range = infer_rep_range(ordered)
    if rep_range is None:
        return None
    low, high = rep_range

    last = ordered[-1]
    top_weight = max((w for _, w in last.sets if w is not None), default=None)
    set_count = len(last.sets)

    if is_stalled:
        if top_weight is None:
            return NextTarget(
                kind="deload",
                weight=None,
                unit=unit,
                target_reps=max(1, low),
                sets=set_count,
                reason=(
                    "Top set has been flat or falling for three weeks. "
                    "Back off to easier sets and rebuild."
                ),
            )
        deloaded = _round_weight(top_weight * (1 - DELOAD_FRACTION), unit)
        return NextTarget(
            kind="deload",
            weight=deloaded,
            unit=unit,
            target_reps=high,
            sets=set_count,
            reason=(
                f"Stalled: top set has been flat or falling for three weeks, "
                f"so drop {int(DELOAD_FRACTION * 100)}% to "
                f"{_fmt(deloaded)} {unit.value} and build back up."
            ),
        )

    hit_top = all(reps >= high for reps, _ in last.sets)

    if hit_top and top_weight is not None:
        increment = _increment(unit, equipment, muscle_group)
        new_weight = _round_weight(top_weight + increment, unit)
        return NextTarget(
            kind="increase",
            weight=new_weight,
            unit=unit,
            target_reps=low,
            sets=set_count,
            reason=(
                f"Every set hit {high} reps at {_fmt(top_weight)} {unit.value}. "
                f"Add {_fmt(increment)} {unit.value} and restart at {low} reps."
            ),
        )

    if hit_top and top_weight is None:
        return NextTarget(
            kind="increase",
            weight=None,
            unit=unit,
            target_reps=high + 1,
            sets=set_count,
            reason=f"Every bodyweight set hit {high} reps. Go for {high + 1} next time.",
        )

    short_index, short_reps, short_weight = next(
        (i, reps, weight) for i, (reps, weight) in enumerate(last.sets) if reps < high
    )
    target_weight = short_weight if short_weight is not None else top_weight
    return NextTarget(
        kind="repeat",
        weight=target_weight,
        unit=unit,
        target_reps=short_reps + 1,
        sets=set_count,
        reason=(
            f"Set {short_index + 1} stopped at {short_reps} reps. Same weight, "
            f"chase {short_reps + 1} on that set."
        ),
    )


def _increment(unit: Unit, equipment: Equipment, muscle_group: MuscleGroup) -> float:
    barbell_lower, other = INCREMENTS[unit]
    if equipment is Equipment.barbell and muscle_group in LOWER_BODY:
        return barbell_lower
    return other


def _round_weight(weight: float, unit: Unit) -> float:
    step = 2.5 if unit is Unit.lb else 1.25
    return round(round(weight / step) * step, 2)


def _fmt(weight: float) -> str:
    return f"{weight:g}"
