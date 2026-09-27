"""Tier 3 exercise-name resolution."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.parsing.resolver import (
    FUZZY_ACCEPT_SCORE,
    ExerciseCandidate,
    MatchKind,
    normalize,
    resolve_exercise,
)
from app.queries import find_exercise_by_name
from app.seed import CATALOG

CANDIDATES = [
    ExerciseCandidate(1, "Barbell Bench Press", ("bench", "bench press", "bb bench", "bp")),
    ExerciseCandidate(2, "Back Squat", ("squat", "squats", "bb squat")),
    ExerciseCandidate(3, "Romanian Deadlift", ("rdl", "rdls", "stiff leg deadlift")),
    ExerciseCandidate(4, "Lateral Raise", ("lat raise", "side raise", "laterals")),
]


def test_exact_canonical_match():
    result = resolve_exercise("Barbell Bench Press", CANDIDATES)
    assert result.kind is MatchKind.exact
    assert result.exercise is not None and result.exercise.id == 1
    assert result.score == 100.0


def test_exact_match_ignores_case_and_punctuation():
    result = resolve_exercise("  barbell  bench-press ", CANDIDATES)
    assert result.kind is MatchKind.exact
    assert result.exercise is not None and result.exercise.id == 1


def test_alias_match():
    result = resolve_exercise("RDLs", CANDIDATES)
    assert result.kind is MatchKind.alias
    assert result.exercise is not None and result.exercise.id == 3


def test_alias_match_on_a_short_form():
    result = resolve_exercise("bp", CANDIDATES)
    assert result.kind is MatchKind.alias
    assert result.exercise is not None and result.exercise.id == 1


def test_fuzzy_match_above_threshold():
    result = resolve_exercise("romanian dead lift", CANDIDATES)
    assert result.kind is MatchKind.fuzzy
    assert result.exercise is not None and result.exercise.id == 3
    assert result.score >= FUZZY_ACCEPT_SCORE


def test_typo_resolves_by_fuzzy_match():
    result = resolve_exercise("lateral raies", CANDIDATES)
    assert result.kind is MatchKind.fuzzy
    assert result.exercise is not None and result.exercise.id == 4


def test_an_unknown_compound_name_is_not_swallowed_by_a_short_alias():
    # token_set_ratio alone scores "jefferson curl" against "curl" at 100.
    result = resolve_exercise("jefferson curl", CANDIDATES)
    assert result.kind is MatchKind.ambiguous
    assert result.exercise is None


def test_a_qualifier_on_a_known_lift_still_resolves():
    result = resolve_exercise("heavy back squat", CANDIDATES)
    assert result.exercise is not None and result.exercise.id == 2


def test_a_qualifier_that_changes_the_target_muscle_blocks_the_match():
    """`pec deck` is chest, `reverse pec deck` is rear delts.

    Fuzzy scorers rate the pair as near-identical, and a live message once
    logged chest work as shoulders because of it.
    """
    candidates = [
        ExerciseCandidate(10, "Rear Delt Fly", ("reverse pec deck", "rear delt flye")),
    ]
    assert resolve_exercise("pec deck", candidates).exercise is None
    # The qualified form still resolves.
    assert resolve_exercise("reverse pec deck", candidates).exercise is not None


def test_qualifier_guard_does_not_block_plain_typos():
    candidates = [ExerciseCandidate(11, "Reverse Pec Deck", ("reverse pec dec",))]
    assert resolve_exercise("reverse pec dek", candidates).exercise is not None


def test_pec_deck_resolves_to_chest_in_the_real_catalog():
    from app.models import MuscleGroup

    catalog = [
        ExerciseCandidate(i, name, tuple(aliases))
        for i, (name, aliases, _, _) in enumerate(CATALOG)
    ]
    result = resolve_exercise("pec deck", catalog)
    assert result.exercise is not None
    assert result.exercise.canonical_name == "Pec Deck"
    by_name = {name: group for name, _, group, _ in CATALOG}
    assert by_name["Pec Deck"] is MuscleGroup.chest


def test_below_threshold_returns_top_candidates():
    result = resolve_exercise("zercher carry", CANDIDATES)
    assert result.kind is MatchKind.ambiguous
    assert result.exercise is None
    assert result.score < FUZZY_ACCEPT_SCORE
    assert 1 <= len(result.candidates) <= 3


def test_candidates_are_distinct_exercises():
    result = resolve_exercise("thruster complex", CANDIDATES)
    ids = [candidate.id for candidate in result.candidates]
    assert len(ids) == len(set(ids))


def test_empty_catalog_is_ambiguous():
    result = resolve_exercise("bench", [])
    assert result.exercise is None
    assert result.candidates == ()


def test_normalize_drops_filler_words():
    assert normalize("did Bench Press today") == "bench press"
    assert normalize("today") == "today"  # never normalizes away to nothing


def test_catalog_aliases_are_unique():
    """Two exercises sharing an alias would make exact matching arbitrary."""
    seen: dict[str, str] = {}
    for canonical, aliases, _, _ in CATALOG:
        for surface in (canonical, *aliases):
            key = normalize(surface)
            assert key not in seen, f"{key!r} claimed by {seen.get(key)} and {canonical}"
            seen[key] = canonical


async def test_find_exercise_by_name_against_the_seeded_catalog(
    seeded_session: AsyncSession, user: User
):
    exercise = await find_exercise_by_name(seeded_session, user.id, "bench")
    assert exercise is not None
    assert exercise.canonical_name == "Barbell Bench Press"


async def test_find_exercise_by_name_returns_none_when_unresolvable(
    seeded_session: AsyncSession, user: User
):
    assert await find_exercise_by_name(seeded_session, user.id, "qqqzzz") is None
