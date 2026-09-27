"""MarkdownV2-safe reply construction.

Every piece of dynamic text goes through :func:`esc` before it reaches a
message. Telegram rejects an unescaped reserved character with a 400, so the
rule here is: build structure with literal markup, interpolate only escaped
values.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from app.analytics.progression import NextTarget
from app.models import MuscleGroup, Unit
from app.schemas import ParsedSet

# Reserved by Telegram's MarkdownV2 parser.
_RESERVED = set(r"_*[]()~`>#+-=|{}.!\\")

MUSCLE_LABEL = {
    MuscleGroup.chest: "Chest",
    MuscleGroup.back: "Back",
    MuscleGroup.quads: "Quads",
    MuscleGroup.hamstrings: "Hamstrings",
    MuscleGroup.glutes: "Glutes",
    MuscleGroup.shoulders: "Shoulders",
    MuscleGroup.biceps: "Biceps",
    MuscleGroup.triceps: "Triceps",
    MuscleGroup.calves: "Calves",
    MuscleGroup.core: "Core",
    MuscleGroup.full_body: "Full body",
}


def esc(text: object) -> str:
    """Escape a value for MarkdownV2."""
    return "".join("\\" + ch if ch in _RESERVED else ch for ch in str(text))


def esc_code(text: object) -> str:
    """Escape a value for use inside a MarkdownV2 code span."""
    return str(text).replace("\\", "\\\\").replace("`", "\\`")


def num(value: float | None) -> str:
    """Trim trailing zeros: 185.0 -> 185, 187.5 -> 187.5."""
    if value is None:
        return "BW"
    return f"{value:.2f}".rstrip("0").rstrip(".")


def weight_label(weight: float | None, unit: Unit) -> str:
    if weight is None:
        return "bodyweight"
    return f"{num(weight)} {unit.value}"


def day_label(day: date) -> str:
    return day.strftime("%a %b %-d")


def sets_word(count: int) -> str:
    return "set" if count == 1 else "sets"


def summarize_sets(sets: Iterable[ParsedSet]) -> str:
    """Collapse runs of identical sets: ``3x8 @ 185 lb, 1x5 @ 195 lb``."""
    groups: list[tuple[int, ParsedSet]] = []
    for entry in sets:
        if groups and _same_shape(groups[-1][1], entry):
            count, first = groups[-1]
            groups[-1] = (count + 1, first)
        else:
            groups.append((1, entry))

    parts = []
    for count, entry in groups:
        piece = f"{count}x{entry.reps}"
        if entry.weight is not None:
            piece += f" @ {num(entry.weight)} {entry.unit.value}"
        else:
            piece += " bodyweight"
        if entry.rpe is not None:
            piece += f" RPE {num(entry.rpe)}"
        if entry.is_warmup:
            piece += " (warmup)"
        parts.append(piece)
    return ", ".join(parts)


def _same_shape(a: ParsedSet, b: ParsedSet) -> bool:
    return (
        a.reps == b.reps
        and a.weight == b.weight
        and a.unit is b.unit
        and a.rpe == b.rpe
        and a.is_warmup == b.is_warmup
    )


def log_confirmation(
    performed_on: date,
    lines: list[tuple[str, list[ParsedSet]]],
    hard_sets: int,
) -> str:
    out = [f"✅ *Logged* · {esc(day_label(performed_on))}"]
    for name, sets in lines:
        out.append(f"*{esc(name)}* — {esc(summarize_sets(sets))}")
    out.append(f"{hard_sets} hard {esc(sets_word(hard_sets))} this session")
    return "\n".join(out)


def target_line(name: str, target: NextTarget) -> str:
    icon = {"increase": "⬆️", "repeat": "➡️", "deload": "⬇️"}[target.kind]
    weight = weight_label(target.weight, target.unit)
    return (
        f"{icon} *{esc(name)}* — {esc(target.sets)}x{esc(target.target_reps)} "
        f"@ {esc(weight)}\n    _{esc(target.reason)}_"
    )


def unparseable_reply() -> str:
    return (
        "🤔 I could not read that as a workout\\.\n\n"
        "Try one of these:\n"
        "`bench 3x8 185`\n"
        "`squat 225 5x3`\n"
        "`ohp 95x5, 95x5, 100x4`"
    )


def missing_reps_reply(exercises: list[str]) -> str:
    names = ", ".join(exercises)
    return (
        f"🤔 I got the weight for *{esc(names)}* but not how many reps\\.\n"
        "I will not guess at that — send it again with the reps, like "
        "`hack squat 200x8`\\."
    )


def parser_unavailable_reply() -> str:
    return (
        "⚠️ The language parser is temporarily unavailable\\.\n"
        "Shorthand still works — try `bench 3x8 185`\\."
    )


def help_text() -> str:
    commands = [
        ("/today", "everything logged today"),
        ("/last <exercise>", "last 3 sessions plus your next target"),
        ("/week", "this week's sessions and hard sets per muscle group"),
        ("/next", "targets for everything trained in the last 10 days"),
        ("/bw 187", "log bodyweight"),
        ("/undo", "pick a recent workout to delete"),
        ("/fix", "replace your most recent workout"),
        ("/dashboard", "a link to your charts"),
        ("/help", "this message"),
    ]
    formats = [
        "bench 3x8 185",
        "squat 225 5x3",
        "ohp 95x5, 95x5, 100x4",
        "deadlift 315x5 @8",
        "curls 3x12 30lb",
        "pullups 3x8",
        "bench 185 5,5,4",
        "bench 3x8 185 / squat 5x5 225",
    ]
    out = ["*Commands*"]
    out += [f"{esc(cmd)} — {esc(desc)}" for cmd, desc in commands]
    out.append("")
    out.append("*Input formats*")
    out.append("Just send your sets, no command needed\\.")
    out += [f"`{esc_code(fmt)}`" for fmt in formats]
    out.append("")
    out.append("Anything less structured goes to the language model, so plain")
    out.append("English like _five sets of eight on incline dumbbell press_ works too\\.")
    return "\n".join(out)
