"""Tier 2 fallback and the full rules -> llm -> resolve pipeline.

The Groq client is always mocked; the suite never needs a live key.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest
from openai import APIConnectionError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ParseMethod, Unit, User
from app.parsing import llm as llm_module
from app.parsing.llm import (
    LlmParseFailure,
    MissingReps,
    ParserUnavailable,
    build_messages,
    parse_llm,
)
from app.parsing.pipeline import NoWorkoutData, parse_message
from app.queries import fetch_set_rows, save_workout

FIVE_BY_EIGHT = (
    '{"exercises": [{"name": "incline dumbbell press", "sets": ['
    + ",".join(
        ['{"reps": 8, "weight": 60, "unit": null, "rpe": null, "is_warmup": false}'] * 5
    )
    + "]}]}"
)


@dataclass
class _Message:
    content: str


@dataclass
class _Choice:
    message: _Message


@dataclass
class _Response:
    choices: list[_Choice]


class FakeCompletions:
    """Replays a scripted list of contents, one per call."""

    def __init__(self, contents: list[str]):
        self.contents = list(contents)
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self.contents:
            raise AssertionError("Groq called more times than the test scripted")
        return _Response(choices=[_Choice(message=_Message(self.contents.pop(0)))])


class FakeGroq:
    def __init__(self, contents: list[str]):
        self.completions = FakeCompletions(contents)
        self.chat = self

    @property
    def calls(self) -> list[dict]:
        return self.completions.calls


class ExplodingGroq:
    def __init__(self) -> None:
        self.chat = self
        self.completions = self

    async def create(self, **kwargs):
        raise APIConnectionError(request=None)  # type: ignore[arg-type]


@pytest.fixture
def fake_groq(monkeypatch: pytest.MonkeyPatch):
    def install(contents: list[str]) -> FakeGroq:
        client = FakeGroq(contents)
        monkeypatch.setattr(llm_module, "get_groq_client", lambda: client)
        return client

    return install


# --------------------------------------------------------------------------
# tier 2
# --------------------------------------------------------------------------


async def test_llm_parses_awkward_phrasing(fake_groq):
    client = fake_groq([FIVE_BY_EIGHT])
    parsed = await parse_llm(
        "did about five sets of eight on incline dumbbell press with the 60s", Unit.lb
    )

    assert parsed is not None
    assert parsed.parse_method is ParseMethod.llm
    (exercise,) = parsed.exercises
    assert exercise.name_raw == "incline dumbbell press"
    assert [(s.reps, s.weight) for s in exercise.sets] == [(8, 60.0)] * 5
    assert len(client.calls) == 1


async def test_llm_request_uses_the_configured_model_and_json_mode(fake_groq):
    client = fake_groq([FIVE_BY_EIGHT])
    await parse_llm("five sets of eight on incline dumbbell press", Unit.lb)

    call = client.calls[0]
    assert call["model"] == "test-model"
    assert call["temperature"] == 0
    assert call["response_format"] == {"type": "json_object"}


async def test_empty_exercise_list_means_no_workout_data(fake_groq):
    fake_groq(['{"exercises": []}'])
    assert await parse_llm("rest day, knee is sore", Unit.lb) is None


async def test_invalid_json_is_retried_exactly_once(fake_groq):
    client = fake_groq(["not json at all", FIVE_BY_EIGHT])
    parsed = await parse_llm("five sets of eight on incline db press", Unit.lb)

    assert parsed is not None
    assert len(client.calls) == 2
    retry_messages = client.calls[1]["messages"]
    assert "invalid" in retry_messages[-1]["content"]


async def test_two_bad_responses_raise_a_parse_failure(fake_groq):
    client = fake_groq(['{"exercises": [{"name": "bench"}]}', "still broken"])
    with pytest.raises(LlmParseFailure):
        await parse_llm("something unreadable", Unit.lb)
    assert len(client.calls) == 2


async def test_api_errors_surface_as_parser_unavailable(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(llm_module, "get_groq_client", ExplodingGroq)
    with pytest.raises(ParserUnavailable):
        await parse_llm("five sets of eight on incline db press", Unit.lb)


async def test_a_weight_without_reps_is_never_invented(fake_groq):
    """A live message ("200 pounds additional weight for 1 set") had no rep
    count. The old schema forced an int, so the retry made one up."""
    client = fake_groq(
        ['{"exercises": [{"name": "hack squat", "sets": ['
         '{"reps": null, "weight": 200, "unit": null, "rpe": null, "is_warmup": false}]}]}']
    )
    with pytest.raises(MissingReps) as caught:
        await parse_llm("Hack Squat 200 pounds additional weight for 1 set", Unit.lb)

    assert caught.value.exercises == ["hack squat"]
    assert len(client.calls) == 1  # no retry: the response was valid, just incomplete


async def test_the_prompt_tells_the_model_to_null_unknown_reps(fake_groq):
    fake_groq([FIVE_BY_EIGHT])
    await parse_llm("whatever", Unit.lb)
    assert "never guess a rep count" in build_messages("x", Unit.lb)[0]["content"].lower()


def test_prompt_carries_the_users_unit_and_few_shots():
    messages = build_messages("squats 5x5", Unit.kg)
    assert messages[0]["role"] == "system"
    assert "kg" in messages[0]["content"]
    assert sum(1 for m in messages if m["role"] == "assistant") == 4
    assert messages[-1] == {"role": "user", "content": "squats 5x5"}


# --------------------------------------------------------------------------
# full pipeline
# --------------------------------------------------------------------------


async def test_shorthand_never_reaches_the_llm(
    seeded_session: AsyncSession, user: User, monkeypatch: pytest.MonkeyPatch
):
    async def explode(*args, **kwargs):
        raise AssertionError("the rules parser should have handled this")

    monkeypatch.setattr("app.parsing.pipeline.parse_llm", explode)

    result = await parse_message("bench 3x8 185", user, seeded_session)
    assert result.parse_method is ParseMethod.rules
    assert result.ambiguous == []
    (resolved,) = result.resolved
    assert resolved.name == "Barbell Bench Press"
    assert len(resolved.sets) == 3


async def test_prose_falls_through_to_the_llm_and_resolves(
    seeded_session: AsyncSession, user: User, fake_groq
):
    fake_groq([FIVE_BY_EIGHT])
    result = await parse_message(
        "did about five sets of eight on incline dumbbell press with the 60s",
        user,
        seeded_session,
    )
    assert result.parse_method is ParseMethod.llm
    (resolved,) = result.resolved
    assert resolved.name == "Incline Dumbbell Press"
    assert len(resolved.sets) == 5


async def test_unknown_names_come_back_as_ambiguous(
    seeded_session: AsyncSession, user: User, fake_groq
):
    fake_groq(
        ['{"exercises": [{"name": "jefferson curl", "sets": ['
         '{"reps": 8, "weight": 95, "unit": null, "rpe": null, "is_warmup": false}]}]}']
    )
    result = await parse_message("jefferson curls, 8 at 95", user, seeded_session)
    assert result.resolved == []
    (ambiguous,) = result.ambiguous
    assert ambiguous.name_raw == "jefferson curl"
    assert 1 <= len(ambiguous.candidates) <= 3


async def test_messages_without_sets_raise(
    seeded_session: AsyncSession, user: User, fake_groq
):
    fake_groq(['{"exercises": []}'])
    with pytest.raises(NoWorkoutData):
        await parse_message("feeling good today", user, seeded_session)


# --------------------------------------------------------------------------
# persistence round trip
# --------------------------------------------------------------------------


async def test_saved_sets_round_trip_with_indexes_and_units(
    seeded_session: AsyncSession, user: User
):
    result = await parse_message("bench 3x8 185 / squat 5x5 225", user, seeded_session)
    await save_workout(
        seeded_session,
        user,
        date(2026, 8, 13),
        "bench 3x8 185 / squat 5x5 225",
        result.parse_method,
        [(item.exercise_id, item.sets) for item in result.resolved],
    )

    rows = await fetch_set_rows(seeded_session, user.id)
    assert len(rows) == 8
    bench = [r for r in rows if r.exercise_name == "Barbell Bench Press"]
    assert [r.set_index for r in bench] == [1, 2, 3]
    assert {r.weight for r in bench} == {185.0}
    assert {r.unit for r in bench} == {Unit.lb}
    assert all(r.performed_on == date(2026, 8, 13) for r in rows)
