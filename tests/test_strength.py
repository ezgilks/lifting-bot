"""Set records, unit conversion, and top-set extraction.

Progress is measured by weight actually lifted, so there is nothing estimated
here to test -- only real numbers picked out of real sets.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.analytics.strength import (
    LB_PER_KG,
    SetRecord,
    convert,
    set_weight_in,
    top_set,
    top_set_weight,
    working_sets,
)
from app.models import Unit

DAY = date(2026, 8, 14)


def s(reps: int, weight: float | None, warmup: bool = False, unit: Unit = Unit.lb) -> SetRecord:
    return SetRecord(performed_on=DAY, reps=reps, weight=weight, unit=unit, is_warmup=warmup)


# --------------------------------------------------------------------------
# units
# --------------------------------------------------------------------------


def test_conversion_is_identity_within_a_unit():
    assert convert(185, Unit.lb, Unit.lb) == 185


def test_kilos_to_pounds():
    assert convert(100, Unit.kg, Unit.lb) == pytest.approx(220.462, abs=0.001)


def test_pounds_to_kilos():
    assert convert(220.462, Unit.lb, Unit.kg) == pytest.approx(100, abs=0.001)


def test_conversion_round_trips():
    assert convert(convert(84, Unit.kg, Unit.lb), Unit.lb, Unit.kg) == pytest.approx(84)


def test_set_weight_in_converts_a_logged_kilo_set():
    assert set_weight_in(s(5, 100, unit=Unit.kg), Unit.lb) == pytest.approx(100 * LB_PER_KG)


def test_bodyweight_sets_have_no_weight():
    assert set_weight_in(s(8, None), Unit.lb) is None


# --------------------------------------------------------------------------
# working sets
# --------------------------------------------------------------------------


def test_working_sets_drops_warmups():
    records = [s(10, 135, warmup=True), s(5, 225)]
    assert working_sets(records) == [s(5, 225)]


# --------------------------------------------------------------------------
# top set
# --------------------------------------------------------------------------


def test_top_set_is_the_heaviest_working_set():
    best = top_set([s(8, 185), s(5, 225), s(8, 205)], Unit.lb)
    assert best is not None
    assert best.weight == 225.0
    assert best.reps == 5


def test_top_set_breaks_ties_on_reps():
    best = top_set([s(5, 225), s(8, 225), s(3, 225)], Unit.lb)
    assert best is not None
    assert (best.weight, best.reps) == (225.0, 8)


def test_top_set_ignores_warmups_even_when_heavier():
    best = top_set([s(1, 405, warmup=True), s(5, 225)], Unit.lb)
    assert best is not None
    assert best.weight == 225.0


def test_top_set_reports_in_the_requested_unit():
    best = top_set([s(5, 100, unit=Unit.kg)], Unit.lb)
    assert best is not None
    assert best.weight == pytest.approx(220.46, abs=0.01)


def test_top_set_falls_back_to_reps_for_bodyweight_only_sessions():
    best = top_set([s(8, None), s(12, None), s(6, None)], Unit.lb)
    assert best is not None
    assert best.weight is None
    assert best.reps == 12


def test_loaded_sets_win_over_bodyweight_sets():
    best = top_set([s(20, None), s(5, 100)], Unit.lb)
    assert best is not None
    assert best.weight == 100.0


def test_top_set_of_nothing_is_none():
    assert top_set([], Unit.lb) is None
    assert top_set([s(10, 135, warmup=True)], Unit.lb) is None


def test_top_set_weight_shortcut():
    assert top_set_weight([s(8, 185), s(3, 245)], Unit.lb) == 245.0
    assert top_set_weight([s(8, None)], Unit.lb) is None
    assert top_set_weight([], Unit.lb) is None
