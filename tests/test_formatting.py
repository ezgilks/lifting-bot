"""MarkdownV2 escaping and the bot's reply construction.

Telegram rejects an unescaped reserved character with a 400, so these guard
the formatting helpers rather than the wording.
"""

from __future__ import annotations

import re
from datetime import date

import pytest

from app.analytics.progression import NextTarget
from app.bot import formatting as fmt
from app.bot.runner import COMMANDS, build_application
from app.models import Unit
from app.schemas import ParsedSet

DAY = date(2026, 8, 13)

# A reserved character is only legal when a backslash precedes it.
_UNESCAPED = re.compile(r"(?<!\\)[_\[\]()~>#+\-=|{}.!]")


def unescaped_outside_markup(text: str) -> list[str]:
    """Reserved characters that are neither escaped nor intentional markup.

    Code spans are dropped entirely (their contents are literal by design).
    Italic delimiters are stripped but their contents are still checked.
    """
    without_code = re.sub(r"`[^`]*`", "", text)
    without_italics = re.sub(r"(?<!\\)_([^_\n]*)(?<!\\)_", r"\1", without_code)
    return _UNESCAPED.findall(without_italics)


def test_esc_escapes_every_reserved_character():
    assert fmt.esc("a.b-c!") == "a\\.b\\-c\\!"
    assert fmt.esc("T-Bar Row (heavy)") == "T\\-Bar Row \\(heavy\\)"


def test_esc_handles_backslashes():
    assert fmt.esc("a\\b") == "a\\\\b"


def test_esc_code_only_escapes_backticks_and_backslashes():
    assert fmt.esc_code("bench 3x8 185") == "bench 3x8 185"
    assert fmt.esc_code("a`b") == "a\\`b"


def test_num_trims_trailing_zeros():
    assert fmt.num(185.0) == "185"
    assert fmt.num(187.5) == "187.5"
    assert fmt.num(None) == "BW"


def test_summarize_sets_collapses_identical_runs():
    sets = [ParsedSet(reps=8, weight=185.0)] * 3 + [ParsedSet(reps=5, weight=195.0)]
    assert fmt.summarize_sets(sets) == "3x8 @ 185 lb, 1x5 @ 195 lb"


def test_summarize_sets_marks_bodyweight_rpe_and_warmups():
    sets = [
        ParsedSet(reps=10, weight=None, is_warmup=True),
        ParsedSet(reps=5, weight=315.0, rpe=8.5),
    ]
    summary = fmt.summarize_sets(sets)
    assert "1x10 bodyweight (warmup)" in summary
    assert "1x5 @ 315 lb RPE 8.5" in summary


def test_log_confirmation_is_fully_escaped():
    text = fmt.log_confirmation(
        DAY,
        [("T-Bar Row", [ParsedSet(reps=8, weight=187.5)] * 3)],
        hard_sets=3,
    )
    assert unescaped_outside_markup(text) == []
    assert "T\\-Bar Row" in text
    assert "187\\.5" in text


def test_log_confirmation_counts_hard_sets_not_pounds():
    text = fmt.log_confirmation(
        DAY, [("Pull Up", [ParsedSet(reps=8, weight=None)] * 3)], hard_sets=3
    )
    assert "3 hard sets" in text
    assert "lb" not in text
    assert unescaped_outside_markup(text) == []


def test_log_confirmation_uses_the_singular_for_one_set():
    text = fmt.log_confirmation(DAY, [("Dip", [ParsedSet(reps=8, weight=None)])], hard_sets=1)
    assert "1 hard set" in text and "hard sets" not in text


def test_target_line_is_fully_escaped():
    target = NextTarget(
        kind="deload",
        weight=167.5,
        unit=Unit.lb,
        target_reps=8,
        sets=3,
        reason="Stalled: flat for three weeks, so drop 10% to 167.5 lb.",
    )
    text = fmt.target_line("Barbell Bench Press", target)
    assert unescaped_outside_markup(text) == []


@pytest.mark.parametrize(
    "text",
    [fmt.help_text(), fmt.unparseable_reply(), fmt.parser_unavailable_reply()],
)
def test_static_replies_are_valid_markdown_v2(text: str):
    assert unescaped_outside_markup(text) == []


def test_muscle_labels_cover_every_group():
    from app.models import MuscleGroup

    assert set(fmt.MUSCLE_LABEL) == set(MuscleGroup)


# --------------------------------------------------------------------------
# wiring
# --------------------------------------------------------------------------


def test_every_advertised_command_has_a_handler():
    application = build_application()
    registered = {
        command
        for group in application.handlers.values()
        for handler in group
        for command in getattr(handler, "commands", ()) or ()
    }
    assert {name for name, _ in COMMANDS} <= registered
