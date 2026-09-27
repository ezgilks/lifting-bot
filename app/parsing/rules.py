"""Tier 1: deterministic regex parser for lifting shorthand.

This handles the shorthand people actually type, with zero API calls. It is
deliberately strict: a segment either matches a known shape confidently or the
whole message is rejected with ``None`` so the LLM fallback can take over.
Partial confidence is failure.

Supported shapes (per exercise segment)::

    bench 3x8 185          sets x reps, then weight
    squat 225 5x3          weight, then sets x reps
    ohp 95x5, 95x5, 100x4  explicit per-set entries
    deadlift 315x5 @8      trailing RPE
    curls 3x12 30lb        explicit unit suffix
    pullups 3x8            bodyweight, no weight
    bench 185 5,5,4        weight, then a rep list
    pullups 8,7,6          bodyweight rep list

Multiple exercises may be separated by newlines, ``;``, `` / ``, or a comma
that is followed by a letter.
"""

from __future__ import annotations

import re

from app.models import ParseMethod, Unit
from app.schemas import ParsedExercise, ParsedSet, ParsedWorkout

# A bare `AxB` with no other weight in the segment is ambiguous: `3x8` means
# three sets of eight, while `315x5` means 315 for five. We split on the
# largest set count anyone realistically writes. Above it, A is a weight.
MAX_PLAUSIBLE_SETS = 10
MAX_REPS = 100

_NUM = r"\d{1,4}(?:\.\d{1,2})?"
_UNIT = r"(?:lbs|lb|kgs|kg|#)"
_X = r"[x×*]"

_SEGMENT_SPLIT = re.compile(r"[\n;]+|\s+/\s+")
# Split on a comma only when an exercise name follows it; commas inside rep
# lists (`185 5,5,4`) are always followed by a digit.
_COMMA_EXERCISE_SPLIT = re.compile(r",\s*(?=[A-Za-z])")

_TRAILING_RPE = re.compile(r"\s*(?:@|rpe)\s*(?P<rpe>\d{1,2}(?:\.\d)?)\s*$", re.IGNORECASE)
_WARMUP_PREFIX = re.compile(r"^(?:warm\s*-?\s*up|w/u|wu)\b[\s:]*", re.IGNORECASE)
_FIRST_DIGIT = re.compile(r"\d")
_HAS_LETTER = re.compile(r"[A-Za-z]")

# weight, then sets x reps  ->  "225 5x3"
_WEIGHT_THEN_SXR = re.compile(
    rf"^(?P<w>{_NUM})\s*(?P<u>{_UNIT})?\s+(?P<sets>\d{{1,2}})\s*{_X}\s*(?P<reps>\d{{1,3}})$",
    re.IGNORECASE,
)
# sets x reps, optional trailing weight  ->  "3x8 185", "3x8", "315x5"
_SXR_THEN_WEIGHT = re.compile(
    rf"^(?P<a>{_NUM})\s*(?P<au>{_UNIT})?\s*{_X}\s*(?P<b>\d{{1,3}})"
    rf"(?:\s+(?P<w>{_NUM})\s*(?P<u>{_UNIT})?)?$",
    re.IGNORECASE,
)
# weight, then a comma separated rep list  ->  "185 5,5,4"
_WEIGHT_THEN_REPLIST = re.compile(
    rf"^(?P<w>{_NUM})\s*(?P<u>{_UNIT})?\s+(?P<reps>\d{{1,3}}(?:\s*,\s*\d{{1,3}})+)$",
    re.IGNORECASE,
)
# bare rep list, bodyweight  ->  "8,7,6"
_BARE_REPLIST = re.compile(r"^\d{1,3}(?:\s*,\s*\d{1,3})+$")
# one element of an explicit per-set list  ->  "95x5", "100x4@9"
_SET_ELEMENT = re.compile(
    rf"^(?P<w>{_NUM})\s*(?P<u>{_UNIT})?\s*{_X}\s*(?P<reps>\d{{1,3}})"
    rf"(?:\s*(?:@|rpe\s*)\s*(?P<rpe>\d{{1,2}}(?:\.\d)?))?$",
    re.IGNORECASE,
)


def parse_rules(raw: str, default_unit: Unit) -> ParsedWorkout | None:
    """Parse a message with regex alone. ``None`` means "not confident"."""
    segments = _split_segments(raw)
    if not segments:
        return None

    exercises: list[ParsedExercise] = []
    for segment in segments:
        parsed = _parse_segment(segment, default_unit)
        if parsed is None:
            return None
        exercises.append(parsed)

    if not exercises:
        return None
    return ParsedWorkout(exercises=exercises, parse_method=ParseMethod.rules)


def _split_segments(raw: str) -> list[str]:
    segments: list[str] = []
    for chunk in _SEGMENT_SPLIT.split(raw.strip()):
        for part in _COMMA_EXERCISE_SPLIT.split(chunk):
            part = part.strip().strip(".")
            if part:
                segments.append(part)
    return segments


def _parse_segment(segment: str, default_unit: Unit) -> ParsedExercise | None:
    text = segment.strip()

    is_warmup = False
    stripped = _WARMUP_PREFIX.sub("", text)
    if stripped != text:
        is_warmup = True
        text = stripped.strip()

    text, segment_rpe = _strip_trailing_rpe(text)
    if not text:
        return None

    digit = _FIRST_DIGIT.search(text)
    if digit is None or digit.start() == 0:
        # No numbers at all, or no exercise name before them.
        return None

    name = text[: digit.start()].strip(" \t:-")
    rest = text[digit.start() :].strip()
    if not name or not _HAS_LETTER.search(name) or not rest:
        return None

    sets = _parse_sets(rest, default_unit)
    if sets is None:
        return None

    if segment_rpe is not None or is_warmup:
        sets = [
            s.model_copy(
                update={
                    "rpe": s.rpe if s.rpe is not None else segment_rpe,
                    "is_warmup": is_warmup or s.is_warmup,
                }
            )
            for s in sets
        ]
    return ParsedExercise(name_raw=name, sets=sets)


def _strip_trailing_rpe(text: str) -> tuple[str, float | None]:
    match = _TRAILING_RPE.search(text)
    if match is None:
        return text, None
    rpe = float(match.group("rpe"))
    if not 1 <= rpe <= 10:
        return text, None
    return text[: match.start()].strip(), rpe


def _parse_sets(rest: str, default_unit: Unit) -> list[ParsedSet] | None:
    """Turn the numeric tail of a segment into concrete sets."""
    elements = [p.strip() for p in rest.split(",")]

    # Explicit per-set list: "95x5, 95x5, 100x4". In a list of two or more
    # `AxB` elements the leading number is always a weight -- nobody repeats
    # a sets x reps shorthand.
    element_matches = [_SET_ELEMENT.match(e) for e in elements]
    if len(elements) > 1 and all(m is not None for m in element_matches):
        sets: list[ParsedSet] = []
        for match in element_matches:
            if match is None:  # pragma: no cover - guarded by the all() above
                return None
            weight, unit = _weight(match.group("w"), match.group("u"), default_unit)
            reps = int(match.group("reps"))
            if not 1 <= reps <= MAX_REPS:
                return None
            rpe = float(match.group("rpe")) if match.group("rpe") else None
            if rpe is not None and not 1 <= rpe <= 10:
                return None
            sets.append(ParsedSet(reps=reps, weight=weight, unit=unit, rpe=rpe))
        return sets

    # "185 5,5,4"
    match = _WEIGHT_THEN_REPLIST.match(rest)
    if match:
        weight, unit = _weight(match.group("w"), match.group("u"), default_unit)
        reps_list = [int(r) for r in match.group("reps").split(",")]
        if not all(1 <= r <= MAX_REPS for r in reps_list):
            return None
        return [ParsedSet(reps=r, weight=weight, unit=unit) for r in reps_list]

    # "8,7,6" -- bodyweight
    if _BARE_REPLIST.match(rest):
        reps_list = [int(r) for r in rest.split(",")]
        if not all(1 <= r <= MAX_REPS for r in reps_list):
            return None
        return [ParsedSet(reps=r, weight=None, unit=default_unit) for r in reps_list]

    # "225 5x3"
    match = _WEIGHT_THEN_SXR.match(rest)
    if match:
        weight, unit = _weight(match.group("w"), match.group("u"), default_unit)
        count = int(match.group("sets"))
        reps = int(match.group("reps"))
        if not 1 <= count <= MAX_PLAUSIBLE_SETS or not 1 <= reps <= MAX_REPS:
            return None
        return [ParsedSet(reps=reps, weight=weight, unit=unit)] * count

    # "3x8 185", "3x8", "315x5"
    match = _SXR_THEN_WEIGHT.match(rest)
    if match:
        return _parse_sxr(match, default_unit)

    return None


def _parse_sxr(match: re.Match[str], default_unit: Unit) -> list[ParsedSet] | None:
    a_raw, a_unit = match.group("a"), match.group("au")
    b = int(match.group("b"))
    trailing_weight = match.group("w")

    if not 1 <= b <= MAX_REPS:
        return None

    if trailing_weight is not None:
        # A trailing weight settles it: A is a set count.
        count = int(float(a_raw))
        if a_unit or "." in a_raw or not 1 <= count <= MAX_PLAUSIBLE_SETS:
            return None
        weight, unit = _weight(trailing_weight, match.group("u"), default_unit)
        return [ParsedSet(reps=b, weight=weight, unit=unit)] * count

    a_is_weight = a_unit is not None or "." in a_raw or float(a_raw) > MAX_PLAUSIBLE_SETS
    if a_is_weight:
        weight, unit = _weight(a_raw, a_unit, default_unit)
        return [ParsedSet(reps=b, weight=weight, unit=unit)]

    count = int(float(a_raw))
    if count < 1:
        return None
    # Bodyweight: "pullups 3x8".
    return [ParsedSet(reps=b, weight=None, unit=default_unit)] * count


def _weight(num: str, unit_token: str | None, default_unit: Unit) -> tuple[float, Unit]:
    value = float(num)
    if unit_token is None:
        return value, default_unit
    token = unit_token.lower()
    if token.startswith("kg"):
        return value, Unit.kg
    return value, Unit.lb
