"""Tier 2: Groq-backed fallback parser for messages the rules parser rejects."""

from __future__ import annotations

import logging
from functools import lru_cache

from openai import AsyncOpenAI, OpenAIError
from pydantic import ValidationError

from app.config import get_settings
from app.models import ParseMethod, Unit
from app.schemas import LlmWorkout, ParsedExercise, ParsedSet, ParsedWorkout

logger = logging.getLogger(__name__)

GROQ_BASE_URL = "https://api.groq.com/openai/v1"


class ParserUnavailable(RuntimeError):
    """The Groq API could not be reached or returned an unusable response."""


class LlmParseFailure(ValueError):
    """Groq answered, but not with data matching the schema after one retry."""


class MissingReps(ValueError):
    """The message named a weight but never said how many reps.

    Guessing here would fabricate training data, so the bot asks instead.
    """

    def __init__(self, exercises: list[str]):
        self.exercises = exercises
        super().__init__(", ".join(exercises))


_SYSTEM_PROMPT = """You extract weightlifting sets from a short message.

Return ONLY a JSON object with this exact schema:
{{
  "exercises": [
    {{
      "name": "<exercise name exactly as the user said it>",
      "sets": [
        {{"reps": <int>, "weight": <number or null>, "unit": "lb" | "kg" | null,
          "rpe": <number 1-10 or null>, "is_warmup": <bool>}}
      ]
    }}
  ]
}}

Rules:
- One entry in "sets" per performed set. "5 sets of 8" means five set objects.
- The user's default unit is {unit}. Use null for "unit" unless they name a different one.
- Bodyweight movements with no added load use "weight": null.
- Dumbbell work stated as "the 60s" means 60 per dumbbell: "weight": 60.
- Never invent sets, weights or exercises that are not in the message.
- If the message gives a weight but never says how many reps, set "reps": null.
  Never guess a rep count.
- If the message contains no workout data at all, return {{"exercises": []}}.
- Output the JSON object and nothing else."""

_FEW_SHOTS: list[tuple[str, str]] = [
    (
        "did five sets of eight on incline dumbbell press with the 60s",
        '{"exercises": [{"name": "incline dumbbell press", "sets": ['
        '{"reps": 8, "weight": 60, "unit": null, "rpe": null, "is_warmup": false},'
        '{"reps": 8, "weight": 60, "unit": null, "rpe": null, "is_warmup": false},'
        '{"reps": 8, "weight": 60, "unit": null, "rpe": null, "is_warmup": false},'
        '{"reps": 8, "weight": 60, "unit": null, "rpe": null, "is_warmup": false},'
        '{"reps": 8, "weight": 60, "unit": null, "rpe": null, "is_warmup": false}]}]}',
    ),
    (
        "warmed up bench with 135 for 10 then worked up to a heavy triple at 245",
        '{"exercises": [{"name": "bench", "sets": ['
        '{"reps": 10, "weight": 135, "unit": null, "rpe": null, "is_warmup": true},'
        '{"reps": 3, "weight": 245, "unit": null, "rpe": null, "is_warmup": false}]}]}',
    ),
    (
        "squats felt heavy today, 3 sets of 5 at 100 kilos, last one was an rpe 9. "
        "then some leg curls, 12 12 10 on the 50",
        '{"exercises": ['
        '{"name": "squats", "sets": ['
        '{"reps": 5, "weight": 100, "unit": "kg", "rpe": null, "is_warmup": false},'
        '{"reps": 5, "weight": 100, "unit": "kg", "rpe": null, "is_warmup": false},'
        '{"reps": 5, "weight": 100, "unit": "kg", "rpe": 9, "is_warmup": false}]},'
        '{"name": "leg curls", "sets": ['
        '{"reps": 12, "weight": 50, "unit": null, "rpe": null, "is_warmup": false},'
        '{"reps": 12, "weight": 50, "unit": null, "rpe": null, "is_warmup": false},'
        '{"reps": 10, "weight": 50, "unit": null, "rpe": null, "is_warmup": false}]}]}',
    ),
    (
        "rest day, knee is still sore",
        '{"exercises": []}',
    ),
]


@lru_cache
def get_groq_client() -> AsyncOpenAI:
    settings = get_settings()
    return AsyncOpenAI(api_key=settings.groq_api_key, base_url=GROQ_BASE_URL, timeout=30.0)


def build_messages(raw: str, unit: Unit) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = [
        {"role": "system", "content": _SYSTEM_PROMPT.format(unit=unit.value)}
    ]
    for user_text, assistant_json in _FEW_SHOTS:
        messages.append({"role": "user", "content": user_text})
        messages.append({"role": "assistant", "content": assistant_json})
    messages.append({"role": "user", "content": raw})
    return messages


async def parse_llm(raw: str, unit: Unit) -> ParsedWorkout | None:
    """Parse via Groq. Returns ``None`` when the message holds no workout data.

    Raises ``LlmParseFailure`` if the model cannot produce valid JSON in two
    attempts, and ``ParserUnavailable`` if the API itself is unreachable.
    """
    settings = get_settings()
    client = get_groq_client()
    messages = build_messages(raw, unit)

    last_error: str | None = None
    for attempt in (1, 2):
        if last_error is not None:
            messages = [
                *messages,
                {"role": "user", "content": f"That response was invalid: {last_error}. "
                                            "Reply again with only the JSON object."},
            ]
        try:
            response = await client.chat.completions.create(
                model=settings.groq_model,
                messages=messages,  # type: ignore[arg-type]
                temperature=0,
                response_format={"type": "json_object"},
            )
        except OpenAIError as exc:
            logger.warning("Groq request failed: %s", exc)
            raise ParserUnavailable(str(exc)) from exc

        content = response.choices[0].message.content or ""
        try:
            payload = LlmWorkout.model_validate_json(content)
        except ValidationError as exc:
            last_error = _short_error(exc)
            logger.warning("Groq response failed validation (attempt %s): %s", attempt, last_error)
            messages = [*messages, {"role": "assistant", "content": content}]
            continue

        return _to_parsed_workout(payload, unit)

    raise LlmParseFailure(last_error or "unparseable response")


def _short_error(exc: ValidationError) -> str:
    parts = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:3]]
    return "; ".join(parts) or str(exc)


def _to_parsed_workout(payload: LlmWorkout, unit: Unit) -> ParsedWorkout | None:
    incomplete = [
        item.name.strip()
        for item in payload.exercises
        if item.name.strip() and any(s.reps is None for s in item.sets)
    ]
    if incomplete:
        raise MissingReps(incomplete)

    exercises = [
        ParsedExercise(
            name_raw=item.name.strip(),
            sets=[
                ParsedSet(
                    reps=s.reps,
                    weight=s.weight,
                    unit=s.unit or unit,
                    rpe=s.rpe,
                    is_warmup=s.is_warmup,
                )
                for s in item.sets
                if s.reps is not None  # guarded by the MissingReps check above
            ],
        )
        for item in payload.exercises
        if item.name.strip()
    ]
    if not exercises:
        return None
    return ParsedWorkout(exercises=exercises, parse_method=ParseMethod.llm)
