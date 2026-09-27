"""Tier 3: map a free-text exercise name onto a catalog row."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from rapidfuzz import fuzz, process

FUZZY_ACCEPT_SCORE = 88
# Guards against token_set_ratio's blind spot for supersets (see below).
MIN_TOKEN_SORT_SCORE = 60
MAX_CANDIDATES = 3

_PUNCT = re.compile(r"[^a-z0-9\s]+")
_WS = re.compile(r"\s+")
# Filler people wrap a name in: "did bench press today". Deliberately short --
# words like "set" or "up" belong to real exercise names.
_NOISE_WORDS = {"today", "yesterday", "did", "i"}

# Words that change *which muscle* a movement trains, not just how it is done.
# "pec deck" and "reverse pec deck" are chest and rear delts respectively, and
# fuzzy scorers rate them as near-identical. If one side carries a qualifier the
# other does not, the match is refused and the user is asked instead.
_QUALIFIERS = frozenset(
    {
        "reverse",
        "incline",
        "decline",
        "front",
        "back",
        "rear",
        "seated",
        "standing",
        "lying",
        "bent",
        "close",
        "wide",
        "narrow",
        "single",
        "one",
        "sumo",
        "high",
        "low",
        "overhead",
        "behind",
        "underhand",
        "overhand",
        "neutral",
        "hanging",
        "kneeling",
        "bulgarian",
        "romanian",
        "hack",
        "goblet",
        "split",
        "walking",
        "good",
    }
)


@dataclass(frozen=True)
class ExerciseCandidate:
    """The subset of an Exercise row the resolver needs. Keeps this pure."""

    id: int
    canonical_name: str
    aliases: tuple[str, ...] = field(default=())


class MatchKind(str, Enum):
    exact = "exact"
    alias = "alias"
    fuzzy = "fuzzy"
    ambiguous = "ambiguous"


@dataclass(frozen=True)
class Resolution:
    kind: MatchKind
    exercise: ExerciseCandidate | None
    score: float
    candidates: tuple[ExerciseCandidate, ...] = ()

    @property
    def resolved(self) -> bool:
        return self.exercise is not None


def normalize(name: str) -> str:
    """Lowercase, drop punctuation, collapse whitespace, drop filler words."""
    text = _PUNCT.sub(" ", name.lower())
    tokens = [t for t in _WS.split(text) if t and t not in _NOISE_WORDS]
    if not tokens:
        tokens = [t for t in _WS.split(text) if t]
    return " ".join(tokens)


def _qualifiers_differ(query: str, surface: str) -> bool:
    """True when one side carries a muscle-changing qualifier the other lacks."""
    query_tokens = set(query.split())
    surface_tokens = set(surface.split())
    return bool((query_tokens ^ surface_tokens) & _QUALIFIERS)


def resolve_exercise(name: str, candidates: list[ExerciseCandidate]) -> Resolution:
    """Resolve ``name`` against the catalog.

    1. Case-insensitive exact match on the canonical name or any alias.
    2. ``token_set_ratio`` fuzzy match, accepted at >= 88.
    3. Otherwise the top 3 candidates for the user to disambiguate.
    """
    query = normalize(name)
    if not query or not candidates:
        return Resolution(MatchKind.ambiguous, None, 0.0, tuple(candidates[:MAX_CANDIDATES]))

    for candidate in candidates:
        if normalize(candidate.canonical_name) == query:
            return Resolution(MatchKind.exact, candidate, 100.0)

    for candidate in candidates:
        if any(normalize(alias) == query for alias in candidate.aliases):
            return Resolution(MatchKind.alias, candidate, 100.0)

    # Every canonical name and alias is a searchable surface for the same row.
    choices: list[str] = []
    owners: list[ExerciseCandidate] = []
    for candidate in candidates:
        for surface in (candidate.canonical_name, *candidate.aliases):
            normalized = normalize(surface)
            if normalized:
                choices.append(normalized)
                owners.append(candidate)

    scored = process.extract(
        query, choices, scorer=fuzz.token_set_ratio, limit=len(choices)
    )
    if not scored:
        return Resolution(MatchKind.ambiguous, None, 0.0, tuple(candidates[:MAX_CANDIDATES]))

    # rapidfuzz yields (choice, score, index).
    for choice, score, index in scored:
        if score < FUZZY_ACCEPT_SCORE:
            break
        # token_set_ratio scores any superset of a surface at 100, so
        # "jefferson curl" would silently become "Barbell Curl". A
        # length-sensitive second opinion rejects that without weakening
        # the tolerance for typos and word-order differences.
        if fuzz.token_sort_ratio(query, choice) < MIN_TOKEN_SORT_SCORE:
            continue
        if _qualifiers_differ(query, choice):
            continue
        return Resolution(MatchKind.fuzzy, owners[index], float(score))

    best_score = scored[0][1]
    top: list[ExerciseCandidate] = []
    for _, _score, index in scored:
        owner = owners[index]
        if owner not in top:
            top.append(owner)
        if len(top) == MAX_CANDIDATES:
            break
    return Resolution(MatchKind.ambiguous, None, float(best_score), tuple(top))
