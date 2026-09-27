"""Set records, unit conversion, and top-set extraction. Pure functions, no I/O.

Progress on a lift is measured by the heaviest working set actually performed.
There is deliberately no estimated 1RM here: every number this module reports
is a weight the lifter really moved.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.models import Unit

LB_PER_KG = 2.20462262


@dataclass(frozen=True)
class SetRecord:
    """One performed set, flattened for analytics."""

    performed_on: date
    reps: int
    weight: float | None
    unit: Unit
    is_warmup: bool = False
    workout_id: int = 0


@dataclass(frozen=True)
class TopSet:
    """The heaviest working set of a session, with the reps done on it."""

    weight: float | None
    reps: int


def convert(weight: float, from_unit: Unit, to_unit: Unit) -> float:
    if from_unit is to_unit:
        return weight
    if from_unit is Unit.kg:
        return weight * LB_PER_KG
    return weight / LB_PER_KG


def set_weight_in(record: SetRecord, unit: Unit) -> float | None:
    if record.weight is None:
        return None
    return convert(record.weight, record.unit, unit)


def working_sets(records: list[SetRecord]) -> list[SetRecord]:
    return [r for r in records if not r.is_warmup]


def top_set(records: list[SetRecord], unit: Unit) -> TopSet | None:
    """Heaviest working set, breaking ties on the most reps at that weight.

    Bodyweight sets (no load) rank by reps alone, and are only considered when
    the session contains no loaded sets.
    """
    candidates = working_sets(records)
    if not candidates:
        return None

    loaded = [(set_weight_in(r, unit), r.reps) for r in candidates if r.weight is not None]
    if loaded:
        weight, reps = max(loaded, key=lambda pair: (pair[0], pair[1]))
        return TopSet(round(weight, 2), reps)

    return TopSet(None, max(r.reps for r in candidates))


def top_set_weight(records: list[SetRecord], unit: Unit) -> float | None:
    """Heaviest working weight in ``unit``, or ``None`` for bodyweight-only."""
    best = top_set(records, unit)
    return None if best is None else best.weight
