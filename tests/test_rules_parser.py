"""Tier 1 parser: every supported shape, and the shapes it must refuse."""

from __future__ import annotations

import pytest

from app.models import ParseMethod, Unit
from app.parsing.rules import parse_rules


def parse(raw: str, unit: Unit = Unit.lb):
    return parse_rules(raw, unit)


def shape(raw: str, unit: Unit = Unit.lb) -> list[tuple[str, list[tuple[int, float | None, str]]]]:
    """(name, [(reps, weight, unit)]) for each exercise, for terse assertions."""
    parsed = parse(raw, unit)
    assert parsed is not None, f"expected {raw!r} to parse"
    return [
        (item.name_raw, [(s.reps, s.weight, s.unit.value) for s in item.sets])
        for item in parsed.exercises
    ]


# --------------------------------------------------------------------------
# sets x reps, then weight
# --------------------------------------------------------------------------


def test_sets_by_reps_then_weight():
    assert shape("bench 3x8 185") == [("bench", [(8, 185.0, "lb")] * 3)]


def test_sets_by_reps_then_weight_with_decimal():
    assert shape("incline db press 4x10 62.5") == [
        ("incline db press", [(10, 62.5, "lb")] * 4)
    ]


def test_spaces_around_the_x():
    assert shape("bench press 5 x 5 225") == [("bench press", [(5, 225.0, "lb")] * 5)]


def test_uppercase_x_and_multiplication_sign():
    assert shape("squat 3X5 275") == [("squat", [(5, 275.0, "lb")] * 3)]
    assert shape("squat 3×5 275") == [("squat", [(5, 275.0, "lb")] * 3)]


# --------------------------------------------------------------------------
# weight, then sets x reps
# --------------------------------------------------------------------------


def test_weight_then_sets_by_reps():
    assert shape("squat 225 5x3") == [("squat", [(3, 225.0, "lb")] * 5)]


def test_weight_with_unit_then_sets_by_reps():
    assert shape("front squat 100kg 3x3") == [("front squat", [(3, 100.0, "kg")] * 3)]


# --------------------------------------------------------------------------
# explicit per-set entries
# --------------------------------------------------------------------------


def test_explicit_per_set_entries():
    assert shape("ohp 95x5, 95x5, 100x4") == [
        ("ohp", [(5, 95.0, "lb"), (5, 95.0, "lb"), (4, 100.0, "lb")])
    ]


def test_per_set_entries_keep_light_weights_as_weights():
    # Two or more `AxB` elements are always weight x reps; nobody repeats a
    # sets x reps shorthand.
    assert shape("lateral raise 15x12, 15x12, 12x12") == [
        ("lateral raise", [(12, 15.0, "lb"), (12, 15.0, "lb"), (12, 12.0, "lb")])
    ]


def test_per_set_entries_with_per_set_rpe():
    parsed = parse("deadlift 315x5@8, 335x3@9.5")
    assert parsed is not None
    rpes = [s.rpe for s in parsed.exercises[0].sets]
    assert rpes == [8.0, 9.5]


# --------------------------------------------------------------------------
# RPE
# --------------------------------------------------------------------------


def test_trailing_rpe_applies_to_the_segment():
    parsed = parse("deadlift 315x5 @8")
    assert parsed is not None
    (exercise,) = parsed.exercises
    assert exercise.name_raw == "deadlift"
    assert [(s.reps, s.weight, s.rpe) for s in exercise.sets] == [(5, 315.0, 8.0)]


def test_rpe_keyword_form():
    parsed = parse("rdl 225x8 rpe 7.5")
    assert parsed is not None
    assert parsed.exercises[0].sets[0].rpe == 7.5


def test_trailing_rpe_spreads_over_every_set():
    parsed = parse("squat 3x5 315 @9")
    assert parsed is not None
    assert [s.rpe for s in parsed.exercises[0].sets] == [9.0, 9.0, 9.0]


# --------------------------------------------------------------------------
# units
# --------------------------------------------------------------------------


def test_pound_suffix():
    assert shape("curls 3x12 30lb") == [("curls", [(12, 30.0, "lb")] * 3)]


def test_kilo_suffix_overrides_the_user_default():
    assert shape("curls 3x12 20kg") == [("curls", [(12, 20.0, "kg")] * 3)]


def test_user_default_unit_is_applied():
    assert shape("bench 3x5 100", Unit.kg) == [("bench", [(5, 100.0, "kg")] * 3)]


def test_hash_suffix_means_pounds():
    assert shape("row 3x10 135#") == [("row", [(10, 135.0, "lb")] * 3)]


# --------------------------------------------------------------------------
# bodyweight
# --------------------------------------------------------------------------


def test_bodyweight_sets_by_reps():
    assert shape("pullups 3x8") == [("pullups", [(8, None, "lb")] * 3)]


def test_bodyweight_rep_list():
    assert shape("pullups 8,7,6") == [
        ("pullups", [(8, None, "lb"), (7, None, "lb"), (6, None, "lb")])
    ]


def test_large_leading_number_is_a_weight_not_a_set_count():
    assert shape("deadlift 315x5") == [("deadlift", [(5, 315.0, "lb")])]


# --------------------------------------------------------------------------
# weight then rep list
# --------------------------------------------------------------------------


def test_weight_then_rep_list():
    assert shape("bench 185 5,5,4") == [
        ("bench", [(5, 185.0, "lb"), (5, 185.0, "lb"), (4, 185.0, "lb")])
    ]


def test_weight_with_unit_then_rep_list():
    assert shape("bench 80kg 5,5,4") == [
        ("bench", [(5, 80.0, "kg"), (5, 80.0, "kg"), (4, 80.0, "kg")])
    ]


# --------------------------------------------------------------------------
# multiple exercises
# --------------------------------------------------------------------------


def test_newline_separated_exercises():
    assert shape("bench 3x8 185\nsquat 5x5 225") == [
        ("bench", [(8, 185.0, "lb")] * 3),
        ("squat", [(5, 225.0, "lb")] * 5),
    ]


def test_semicolon_separated_exercises():
    assert [name for name, _ in shape("bench 3x8 185; squat 5x5 225")] == ["bench", "squat"]


def test_slash_separated_exercises():
    assert [name for name, _ in shape("bench 3x8 185 / squat 5x5 225")] == ["bench", "squat"]


def test_comma_separated_exercises_split_on_the_name():
    assert [name for name, _ in shape("curls 3x12 30lb, hammer curls 3x10 25lb")] == [
        "curls",
        "hammer curls",
    ]


# --------------------------------------------------------------------------
# warmups and bookkeeping
# --------------------------------------------------------------------------


def test_warmup_prefix_marks_the_sets():
    parsed = parse("warmup bench 135x5")
    assert parsed is not None
    assert parsed.exercises[0].name_raw == "bench"
    assert all(s.is_warmup for s in parsed.exercises[0].sets)


def test_parse_method_is_recorded():
    parsed = parse("bench 3x8 185")
    assert parsed is not None
    assert parsed.parse_method is ParseMethod.rules


# --------------------------------------------------------------------------
# must refuse
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "hello how are you",
        "bench",
        "3x8",
        "bench 185",
        "felt strong today, might go for a pr soon",
        "bench 3x8 185 / squat",
        "did about five sets of eight on incline dumbbell press with the 60s",
    ],
)
def test_returns_none_when_not_confident(raw: str):
    assert parse(raw) is None


def test_one_bad_segment_rejects_the_whole_message():
    assert parse("bench 3x8 185\nsomething I mumbled") is None
