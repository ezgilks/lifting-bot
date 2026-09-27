"""Trend fitting, stall detection and next-session targets."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.analytics.progression import (
    SessionPoint,
    SessionSets,
    analyze_trend,
    detect_stall,
    fit_trend,
    infer_rep_range,
    next_target,
)
from app.models import Equipment, MuscleGroup, Unit

TODAY = date(2026, 8, 13)


def point(days_ago: int, top_weight: float) -> SessionPoint:
    return SessionPoint(performed_on=TODAY - timedelta(days=days_ago), top_weight=top_weight)


def session(days_ago: int, sets: list[tuple[int, float | None]]) -> SessionSets:
    return SessionSets(performed_on=TODAY - timedelta(days=days_ago), sets=tuple(sets))


# --------------------------------------------------------------------------
# trend fitting
# --------------------------------------------------------------------------


def test_slope_on_a_known_linear_series():
    # Top set climbing 5 lb every 7 days is exactly +5 lb per week.
    points = [point(21, 100), point(14, 105), point(7, 110), point(0, 115)]
    fit = fit_trend(points)
    assert fit is not None
    assert fit.slope_per_week == pytest.approx(5.0)
    assert fit.intercept == pytest.approx(100.0)
    assert fit.sessions == 4
    assert fit.first_session_on == TODAY - timedelta(days=21)


def test_slope_is_negative_on_a_declining_series():
    fit = fit_trend([point(21, 120), point(14, 115), point(7, 110), point(0, 105)])
    assert fit is not None
    assert fit.slope_per_week == pytest.approx(-5.0)


def test_least_squares_smooths_a_noisy_series():
    # Sxy/Sxx = 189/245 = 0.771428 per day -> 5.4 per week.
    fit = fit_trend([point(21, 100), point(14, 103), point(7, 112), point(0, 115)])
    assert fit is not None
    assert fit.slope_per_week == pytest.approx(5.4)


def test_a_single_session_has_no_trend():
    assert fit_trend([point(0, 100)]) is None


def test_sessions_on_one_day_have_no_trend():
    assert fit_trend([point(3, 100), point(3, 110)]) is None


def test_analyze_trend_needs_four_sessions_in_the_window():
    three = [point(20, 100), point(13, 105), point(6, 110)]
    assert analyze_trend(three, TODAY) is None
    assert analyze_trend([*three, point(0, 115)], TODAY) is not None


def test_analyze_trend_ignores_sessions_older_than_eight_weeks():
    points = [point(120, 50), point(20, 100), point(13, 105), point(6, 110)]
    fit = analyze_trend(points, TODAY)
    assert fit is None  # only three sessions land inside the window


# --------------------------------------------------------------------------
# stall detection
# --------------------------------------------------------------------------


def test_flat_three_weeks_is_a_stall():
    points = [point(20, 200), point(13, 200), point(6, 200)]
    assert detect_stall(points, TODAY) is True


def test_declining_three_weeks_is_a_stall():
    points = [point(20, 205), point(13, 200), point(6, 195)]
    assert detect_stall(points, TODAY) is True


def test_rising_three_weeks_is_not_a_stall():
    points = [point(20, 190), point(13, 200), point(6, 210)]
    assert detect_stall(points, TODAY) is False


def test_two_sessions_are_not_enough_to_call_a_stall():
    assert detect_stall([point(13, 200), point(6, 200)], TODAY) is False


def test_old_flat_sessions_do_not_trigger_a_stall():
    points = [point(60, 200), point(50, 200), point(40, 200)]
    assert detect_stall(points, TODAY) is False


# --------------------------------------------------------------------------
# rep range
# --------------------------------------------------------------------------


def test_rep_range_comes_from_the_trailing_four_sessions():
    sessions = [
        session(40, [(15, 100.0)]),  # outside the lookback
        session(21, [(6, 185.0), (6, 185.0)]),
        session(14, [(7, 185.0), (6, 185.0)]),
        session(7, [(8, 185.0), (7, 185.0)]),
        session(0, [(8, 185.0), (8, 185.0)]),
    ]
    assert infer_rep_range(sessions) == (6, 8)


def test_rep_range_is_none_without_sets():
    assert infer_rep_range([]) is None


# --------------------------------------------------------------------------
# next-session targets
# --------------------------------------------------------------------------


PROGRESSING = [
    session(21, [(6, 185.0), (6, 185.0), (6, 185.0)]),
    session(14, [(7, 185.0), (7, 185.0), (6, 185.0)]),
    session(7, [(8, 185.0), (8, 185.0), (7, 185.0)]),
]


def test_increase_when_every_set_hits_the_top_of_the_range():
    sessions = [*PROGRESSING, session(0, [(8, 185.0), (8, 185.0), (8, 185.0)])]
    target = next_target(sessions, Unit.lb, Equipment.barbell, MuscleGroup.chest)
    assert target is not None
    assert target.kind == "increase"
    assert target.weight == pytest.approx(187.5)  # +2.5 lb, upper body
    assert target.target_reps == 6  # back to the bottom of the range
    assert target.sets == 3


def test_barbell_lower_body_gets_the_larger_jump():
    sessions = [*PROGRESSING, session(0, [(8, 185.0), (8, 185.0), (8, 185.0)])]
    target = next_target(sessions, Unit.lb, Equipment.barbell, MuscleGroup.quads)
    assert target is not None
    assert target.weight == pytest.approx(190.0)  # +5 lb


def test_metric_increments():
    sessions = [
        session(14, [(6, 100.0), (6, 100.0)]),
        session(7, [(7, 100.0), (7, 100.0)]),
        session(0, [(8, 100.0), (8, 100.0)]),
    ]
    upper = next_target(sessions, Unit.kg, Equipment.dumbbell, MuscleGroup.shoulders)
    lower = next_target(sessions, Unit.kg, Equipment.barbell, MuscleGroup.glutes)
    assert upper is not None and upper.weight == pytest.approx(101.25)
    assert lower is not None and lower.weight == pytest.approx(102.5)


def test_repeat_when_a_set_fell_short():
    sessions = [*PROGRESSING, session(0, [(8, 185.0), (8, 185.0), (7, 185.0)])]
    target = next_target(sessions, Unit.lb, Equipment.barbell, MuscleGroup.chest)
    assert target is not None
    assert target.kind == "repeat"
    assert target.weight == pytest.approx(185.0)
    assert target.target_reps == 8  # one more on the set that fell short
    assert "Set 3" in target.reason


def test_deload_overrides_everything_when_stalled():
    sessions = [*PROGRESSING, session(0, [(8, 185.0), (8, 185.0), (8, 185.0)])]
    target = next_target(
        sessions, Unit.lb, Equipment.barbell, MuscleGroup.chest, is_stalled=True
    )
    assert target is not None
    assert target.kind == "deload"
    assert target.weight == pytest.approx(167.5)  # 185 - 10%, rounded to the plate
    assert "flat or falling" in target.reason


def test_bodyweight_progression_adds_a_rep():
    sessions = [
        session(14, [(8, None), (8, None)]),
        session(7, [(8, None), (8, None)]),
        session(0, [(8, None), (8, None)]),
    ]
    target = next_target(sessions, Unit.lb, Equipment.bodyweight, MuscleGroup.back)
    assert target is not None
    assert target.kind == "increase"
    assert target.weight is None
    assert target.target_reps == 9


def test_no_history_means_no_target():
    assert next_target([], Unit.lb, Equipment.barbell, MuscleGroup.chest) is None
