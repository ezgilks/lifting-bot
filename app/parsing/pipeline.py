"""Orchestrates the parsing tiers: rules -> llm -> resolve."""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Exercise, ParseMethod, User
from app.parsing.llm import parse_llm
from app.parsing.resolver import ExerciseCandidate, resolve_exercise
from app.parsing.rules import parse_rules
from app.schemas import ParsedSet

logger = logging.getLogger(__name__)

# Since-boot counters. All-time totals come from Workout.parse_method.
PARSER_COUNTERS: Counter[str] = Counter()


class NoWorkoutData(ValueError):
    """Neither tier found any sets in the message."""


@dataclass(frozen=True)
class ResolvedExercise:
    exercise_id: int
    name: str
    sets: list[ParsedSet]


@dataclass(frozen=True)
class AmbiguousExercise:
    name_raw: str
    candidates: tuple[ExerciseCandidate, ...]
    sets: list[ParsedSet]


@dataclass(frozen=True)
class PipelineResult:
    parse_method: ParseMethod
    resolved: list[ResolvedExercise]
    ambiguous: list[AmbiguousExercise]

    @property
    def has_anything(self) -> bool:
        return bool(self.resolved or self.ambiguous)


async def load_catalog(session: AsyncSession, user_id: int) -> list[ExerciseCandidate]:
    """Built-in exercises plus this user's custom ones."""
    rows = await session.scalars(
        select(Exercise).where(
            or_(Exercise.is_custom.is_(False), Exercise.owner_user_id == user_id)
        )
    )
    return [
        ExerciseCandidate(
            id=row.id,
            canonical_name=row.canonical_name,
            aliases=tuple(row.aliases or ()),
        )
        for row in rows
    ]


async def parse_message(raw: str, user: User, session: AsyncSession) -> PipelineResult:
    """Run the full pipeline for one inbound message.

    Raises ``NoWorkoutData`` when the message holds no sets, and propagates
    ``ParserUnavailable`` / ``LlmParseFailure`` from the Groq tier.
    """
    parsed = parse_rules(raw, user.unit)
    if parsed is not None:
        PARSER_COUNTERS["rules"] += 1
        logger.info("rules parser handled message (%s exercises)", len(parsed.exercises))
    else:
        try:
            parsed = await parse_llm(raw, user.unit)
        except Exception:
            PARSER_COUNTERS["llm_failures"] += 1
            raise
        if parsed is None:
            raise NoWorkoutData(raw)
        PARSER_COUNTERS["llm"] += 1
        logger.info("llm parser handled message (%s exercises)", len(parsed.exercises))

    catalog = await load_catalog(session, user.id)

    resolved: list[ResolvedExercise] = []
    ambiguous: list[AmbiguousExercise] = []
    for item in parsed.exercises:
        resolution = resolve_exercise(item.name_raw, catalog)
        if resolution.exercise is not None:
            resolved.append(
                ResolvedExercise(
                    exercise_id=resolution.exercise.id,
                    name=resolution.exercise.canonical_name,
                    sets=list(item.sets),
                )
            )
        else:
            ambiguous.append(
                AmbiguousExercise(
                    name_raw=item.name_raw,
                    candidates=resolution.candidates,
                    sets=list(item.sets),
                )
            )

    result = PipelineResult(parsed.parse_method, resolved, ambiguous)
    if not result.has_anything:
        raise NoWorkoutData(raw)
    return result
