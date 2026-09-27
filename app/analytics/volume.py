"""Training volume as hard sets. Pure functions, no I/O.

Volume here means *sets*, not pounds lifted: weekly hard sets per muscle group
is the metric this app is built around.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date

from app.analytics.strength import convert
from app.models import MuscleGroup, Unit


@dataclass(frozen=True)
class BodyweightRecord:
    recorded_on: date
    weight: float
    unit: Unit


@dataclass(frozen=True)
class GroupedSet:
    """A set tagged with the muscle group it trained."""

    performed_on: date
    muscle_group: MuscleGroup
    is_warmup: bool = False


def iso_week_key(day: date) -> str:
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


def week_start(day: date) -> date:
    return day.fromordinal(day.toordinal() - day.isoweekday() + 1)


def weekly_hard_sets(sets: list[GroupedSet]) -> dict[str, Counter[MuscleGroup]]:
    """Working sets per muscle group, bucketed by ISO week."""
    buckets: dict[str, Counter[MuscleGroup]] = {}
    for item in sets:
        if item.is_warmup:
            continue
        buckets.setdefault(iso_week_key(item.performed_on), Counter())[item.muscle_group] += 1
    return buckets


def hard_sets_for_week(sets: list[GroupedSet], day: date) -> Counter[MuscleGroup]:
    """Hard sets per muscle group for the ISO week containing ``day``."""
    return weekly_hard_sets(sets).get(iso_week_key(day), Counter())


def total_hard_sets(sets: list[GroupedSet]) -> int:
    return sum(1 for item in sets if not item.is_warmup)


def latest_bodyweight(
    entries: list[BodyweightRecord], unit: Unit
) -> tuple[float, date] | None:
    """Most recently recorded bodyweight, converted to ``unit``."""
    if not entries:
        return None
    newest = max(entries, key=lambda e: e.recorded_on)
    return round(convert(newest.weight, newest.unit, unit), 2), newest.recorded_on


def current_streak(session_days: list[date], today: date) -> int:
    """Number of sessions in the current unbroken run.

    The run must reach today or yesterday, and tolerates a single rest day
    between sessions.
    """
    if not session_days:
        return 0
    days = sorted(set(session_days), reverse=True)
    if (today - days[0]).days > 1:
        return 0

    streak = 1
    for previous, current in zip(days, days[1:], strict=False):
        if (previous - current).days <= 2:
            streak += 1
        else:
            break
    return streak
