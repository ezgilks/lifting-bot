"""Telegram command, message and callback handlers."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from app.analytics.progression import NextTarget, detect_stall, next_target
from app.analytics.volume import GroupedSet, hard_sets_for_week, total_hard_sets
from app.api.auth import dashboard_link
from app.bot import formatting as fmt
from app.db import get_session_factory
from app.models import MuscleGroup, ParseMethod, Unit, User
from app.parsing.llm import LlmParseFailure, MissingReps, ParserUnavailable
from app.parsing.pipeline import AmbiguousExercise, NoWorkoutData, parse_message
from app.queries import (
    SetRow,
    build_session_points,
    build_session_sets,
    create_custom_exercise,
    delete_workout,
    fetch_set_rows,
    find_exercise_by_name,
    get_exercise,
    get_or_create_user,
    get_owned_workout,
    group_by_workout,
    latest_workout,
    log_bodyweight,
    recent_workouts,
    save_workout,
)
from app.schemas import ParsedSet

logger = logging.getLogger(__name__)

PENDING_KEY = "pending_log"
NEXT_TARGET_WINDOW_DAYS = 10
UNDO_CHOICES = 5


# --------------------------------------------------------------------------
# plumbing
# --------------------------------------------------------------------------


async def _reply(update: Update, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    message = update.effective_message
    if message is None:
        return
    await message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=markup)


async def _resolve_user(update: Update, session: AsyncSession) -> User:
    chat = update.effective_chat
    if chat is None:  # pragma: no cover - every handler here is chat-scoped
        raise RuntimeError("handler invoked outside a chat")
    name = update.effective_user.full_name if update.effective_user else None
    user, _ = await get_or_create_user(session, chat.id, name)
    return user


def _session():
    return get_session_factory()()


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with _session() as session:
        user = await _resolve_user(update, session)
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Pounds (lb)", callback_data="u:lb"),
                InlineKeyboardButton("Kilograms (kg)", callback_data="u:kg"),
            ]
        ]
    )
    greeting = user.display_name or "lifter"
    await _reply(
        update,
        f"👋 Hey {fmt.esc(greeting)}\\.\n\n"
        "Send me your sets and I will log them\\. For example:\n"
        "`bench 3x8 185`\n\n"
        "First, which units do you lift in?",
        keyboard,
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply(update, fmt.help_text())


async def today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with _session() as session:
        user = await _resolve_user(update, session)
        day = user.today()
        rows = await fetch_set_rows(session, user.id, since=day)
        if not rows:
            await _reply(update, "Nothing logged today yet\\.")
            return

    lines = [f"📋 *Today* · {fmt.esc(fmt.day_label(day))}"]
    for name, sets in _by_exercise(rows):
        lines.append(f"*{fmt.esc(name)}* — {fmt.esc(fmt.summarize_sets(sets))}")
    hard = total_hard_sets(_grouped(rows))
    lines.append(f"*{hard}* hard {fmt.esc(fmt.sets_word(hard))}")
    await _reply(update, "\n".join(lines))


async def last(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = " ".join(context.args or []).strip()
    if not query:
        await _reply(update, "Usage: `/last bench`")
        return

    async with _session() as session:
        user = await _resolve_user(update, session)
        exercise = await find_exercise_by_name(session, user.id, query)
        if exercise is None:
            await _reply(update, f"I do not know an exercise called *{fmt.esc(query)}*\\.")
            return
        rows = await fetch_set_rows(session, user.id, exercise_id=exercise.id)

    if not rows:
        await _reply(update, f"No sets logged for *{fmt.esc(exercise.canonical_name)}* yet\\.")
        return

    sessions = group_by_workout(rows)[-3:]
    lines = [f"📈 *{fmt.esc(exercise.canonical_name)}* · last {len(sessions)} sessions"]
    for _, performed_on, items in reversed(sessions):
        lines.append(
            f"*{fmt.esc(fmt.day_label(performed_on))}* — "
            f"{fmt.esc(fmt.summarize_sets(_to_parsed(items)))}"
        )

    target = _target_for(rows, user)
    if target is not None:
        lines.append("")
        lines.append("*Next session*")
        lines.append(fmt.target_line(exercise.canonical_name, target))
    await _reply(update, "\n".join(lines))


async def week(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with _session() as session:
        user = await _resolve_user(update, session)
        day = user.today()
        rows = await fetch_set_rows(session, user.id, since=day - timedelta(days=21))

    this_week = [r for r in rows if _same_week(r.performed_on, day)]
    last_week = [r for r in rows if _same_week(r.performed_on, day - timedelta(days=7))]

    if not this_week:
        await _reply(update, "No sessions logged this week yet\\.")
        return

    sessions = len({r.workout_id for r in this_week})
    hard = hard_sets_for_week(_grouped(this_week), day)
    total = total_hard_sets(_grouped(this_week))
    previous = total_hard_sets(_grouped(last_week))

    lines = [
        f"🗓 *Week of {fmt.esc(fmt.day_label(_week_start(day)))}*",
        f"Sessions: *{sessions}*",
        f"Hard sets: *{total}*",
    ]
    if previous:
        delta = total - previous
        sign = "▲" if delta >= 0 else "▼"
        lines.append(
            f"vs last week: {fmt.esc(sign)} {abs(delta)} "
            f"\\({previous} → {total}\\)"
        )
    lines.append("")
    lines.append("*Hard sets by muscle group*")
    for group, count in sorted(hard.items(), key=lambda kv: (-kv[1], kv[0].value)):
        lines.append(f"{fmt.esc(fmt.MUSCLE_LABEL[group])}: *{count}*")
    await _reply(update, "\n".join(lines))


async def next_targets(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with _session() as session:
        user = await _resolve_user(update, session)
        cutoff = user.today() - timedelta(days=NEXT_TARGET_WINDOW_DAYS)
        recent = await fetch_set_rows(session, user.id, since=cutoff)
        exercise_ids = {r.exercise_id for r in recent}
        histories = {
            exercise_id: await fetch_set_rows(session, user.id, exercise_id=exercise_id)
            for exercise_id in exercise_ids
        }

    if not histories:
        await _reply(update, f"Nothing trained in the last {NEXT_TARGET_WINDOW_DAYS} days\\.")
        return

    lines = ["🎯 *Next session targets*"]
    for _, rows in sorted(histories.items(), key=lambda kv: kv[1][-1].performed_on):
        target = _target_for(rows, user)
        if target is None:
            continue
        lines.append(fmt.target_line(rows[-1].exercise_name, target))
    if len(lines) == 1:
        await _reply(update, "Not enough history yet to recommend targets\\.")
        return
    await _reply(update, "\n".join(lines))


async def bodyweight(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    raw = " ".join(context.args or []).strip()
    value, unit = _parse_bodyweight(raw)
    if value is None:
        await _reply(update, "Usage: `/bw 187` or `/bw 85kg`")
        return

    async with _session() as session:
        user = await _resolve_user(update, session)
        entry_unit = unit or user.unit
        await log_bodyweight(session, user.id, value, entry_unit, user.today())
    await _reply(
        update,
        f"⚖️ Bodyweight logged: *{fmt.esc(fmt.num(value))} {fmt.esc(entry_unit.value)}*",
    )


async def undo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Pick any of the last few workouts to delete, not just the newest one."""
    async with _session() as session:
        user = await _resolve_user(update, session)
        workouts = await recent_workouts(session, user.id, limit=UNDO_CHOICES)
        if not workouts:
            await _reply(update, "Nothing to undo\\.")
            return
        rows = await fetch_set_rows(session, user.id)

    by_workout = {w.id: [r for r in rows if r.workout_id == w.id] for w in workouts}
    lines = ["🗑 *Which workout should I delete?*"]
    buttons = []
    for index, workout in enumerate(workouts, start=1):
        summary = ", ".join(
            f"{name} {fmt.summarize_sets(sets)}"
            for name, sets in _by_exercise(by_workout[workout.id])
        )
        lines.append(
            f"*{index}\\.* {fmt.esc(fmt.day_label(workout.performed_on))} — "
            f"{fmt.esc(summary)}"
        )
        buttons.append(
            [InlineKeyboardButton(f"{index}. Delete", callback_data=f"d:{workout.id}")]
        )
    buttons.append([InlineKeyboardButton("✖️ Cancel", callback_data="d:no")])
    await _reply(update, "\n".join(lines), InlineKeyboardMarkup(buttons))


async def fix(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Replace the most recent workout with a corrected message."""
    corrected = " ".join(context.args or []).strip()
    if not corrected:
        await _reply(
            update,
            "Send the corrected version with the command, like\n"
            "`/fix hack squat 200x6`\\.",
        )
        return

    async with _session() as session:
        user = await _resolve_user(update, session)
        workout = await latest_workout(session, user.id)
        if workout is None:
            await _reply(update, "There is nothing logged to fix yet\\.")
            return

        try:
            result = await parse_message(corrected, user, session)
        except NoWorkoutData:
            await _reply(update, fmt.unparseable_reply())
            return
        except ParserUnavailable:
            await _reply(update, fmt.parser_unavailable_reply())
            return
        except MissingReps as exc:
            await _reply(update, fmt.missing_reps_reply(exc.exercises))
            return
        except LlmParseFailure:
            await _reply(update, fmt.unparseable_reply())
            return

        if result.ambiguous:
            names = ", ".join(item.name_raw for item in result.ambiguous)
            await _reply(
                update,
                f"I could not place *{fmt.esc(names)}*\\. Send it as a normal message "
                "so I can offer you the options\\.",
            )
            return

        old_day = workout.performed_on
        await delete_workout(session, workout.id)
        entries = [(item.exercise_id, item.name, item.sets) for item in result.resolved]
        await _persist_and_confirm(
            update, session, user, corrected, result.parse_method, entries,
            performed_on=old_day, prefix="♻️ Replaced your last workout\\.",
        )


async def dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with _session() as session:
        user = await _resolve_user(update, session)
    link = dashboard_link(user.id)
    await _reply(
        update,
        f"📊 Your dashboard \\(valid 24 hours\\):\n{fmt.esc(link)}",
    )


# --------------------------------------------------------------------------
# workout logging
# --------------------------------------------------------------------------


async def log_workout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None or not message.text:
        return
    raw = message.text.strip()

    async with _session() as session:
        user = await _resolve_user(update, session)
        try:
            result = await parse_message(raw, user, session)
        except NoWorkoutData:
            await _reply(update, fmt.unparseable_reply())
            return
        except ParserUnavailable:
            await _reply(update, fmt.parser_unavailable_reply())
            return
        except MissingReps as exc:
            await _reply(update, fmt.missing_reps_reply(exc.exercises))
            return
        except LlmParseFailure:
            await _reply(
                update,
                "🤔 I could not pin down the sets in that\\. Could you rephrase it, "
                "or use shorthand like `bench 3x8 185`?",
            )
            return

        entries = [(item.exercise_id, item.name, item.sets) for item in result.resolved]
        if not result.ambiguous:
            await _persist_and_confirm(update, session, user, raw, result.parse_method, entries)
            return

        if context.chat_data is not None:
            context.chat_data[PENDING_KEY] = {
                "source": raw,
                "method": result.parse_method,
                "entries": entries,
                "queue": list(result.ambiguous),
                "awaiting_name": None,
                "awaiting_sets": None,
            }
        await _ask_next_ambiguous(update, context)


async def _ask_next_ambiguous(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    pending = _pending(context)
    if pending is None:
        return
    item: AmbiguousExercise = pending["queue"][0]
    buttons = [
        [InlineKeyboardButton(candidate.canonical_name, callback_data=f"p:{candidate.id}")]
        for candidate in item.candidates
    ]
    buttons.append([InlineKeyboardButton("➕ New exercise", callback_data="p:new")])
    buttons.append([InlineKeyboardButton("✖️ Cancel", callback_data="x")])
    await _reply(
        update,
        f"❓ What is *{fmt.esc(item.name_raw)}*?\n"
        f"_{fmt.esc(fmt.summarize_sets(item.sets))}_",
        InlineKeyboardMarkup(buttons),
    )


async def _persist_and_confirm(
    update: Update,
    session: AsyncSession,
    user: User,
    raw: str,
    parse_method: ParseMethod,
    entries: list[tuple[int, str, list[ParsedSet]]],
    performed_on: date | None = None,
    prefix: str | None = None,
) -> None:
    day = performed_on or user.today()
    await save_workout(
        session,
        user,
        day,
        raw,
        parse_method,
        [(exercise_id, sets) for exercise_id, _, sets in entries],
    )

    hard_sets = sum(1 for _, _, sets in entries for s in sets if not s.is_warmup)
    body = fmt.log_confirmation(
        day, [(name, sets) for _, name, sets in entries], hard_sets
    )
    await _reply(update, f"{prefix}\n{body}" if prefix else body)


# --------------------------------------------------------------------------
# callbacks
# --------------------------------------------------------------------------


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return
    await query.answer()
    data = query.data

    if data.startswith("u:"):
        await _set_unit(update, data.removeprefix("u:"))
    elif data == "x":
        if context.chat_data is not None:
            context.chat_data.pop(PENDING_KEY, None)
        await _reply(update, "Cancelled, nothing was logged\\.")
    elif data == "p:new":
        await _prompt_muscle_group(update, context)
    elif data.startswith("p:"):
        await _pick_exercise(update, context, int(data.removeprefix("p:")))
    elif data.startswith("g:"):
        await _create_and_pick(update, context, data.removeprefix("g:"))
    elif data.startswith("d:"):
        await _confirm_undo(update, data.removeprefix("d:"))


async def _set_unit(update: Update, value: str) -> None:
    unit = Unit.kg if value == "kg" else Unit.lb
    async with _session() as session:
        user = await _resolve_user(update, session)
        user.unit = unit
        await session.commit()
    await _reply(
        update,
        f"Units set to *{fmt.esc(unit.value)}*\\. Send `bench 3x8 185` to log your first sets, "
        "or /help for everything I understand\\.",
    )


async def _prompt_muscle_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    pending = _pending(context)
    if pending is None:
        await _reply(update, "That prompt expired\\. Send the workout again\\.")
        return
    item: AmbiguousExercise = pending["queue"][0]
    pending["awaiting_name"] = item.name_raw

    groups = list(MuscleGroup)
    buttons = [
        [
            InlineKeyboardButton(fmt.MUSCLE_LABEL[group], callback_data=f"g:{group.value}")
            for group in groups[index : index + 2]
        ]
        for index in range(0, len(groups), 2)
    ]
    await _reply(
        update,
        f"Which muscle group does *{fmt.esc(item.name_raw)}* train?",
        InlineKeyboardMarkup(buttons),
    )


async def _create_and_pick(
    update: Update, context: ContextTypes.DEFAULT_TYPE, group_value: str
) -> None:
    pending = _pending(context)
    if pending is None or not pending.get("awaiting_name"):
        await _reply(update, "That prompt expired\\. Send the workout again\\.")
        return
    try:
        group = MuscleGroup(group_value)
    except ValueError:
        await _reply(update, "Unknown muscle group\\.")
        return

    async with _session() as session:
        user = await _resolve_user(update, session)
        exercise = await create_custom_exercise(
            session, user.id, pending["awaiting_name"], group
        )
    pending["awaiting_name"] = None
    await _reply(update, f"Created *{fmt.esc(exercise.canonical_name)}*\\.")
    await _advance(update, context, exercise.id, exercise.canonical_name)


async def _pick_exercise(
    update: Update, context: ContextTypes.DEFAULT_TYPE, exercise_id: int
) -> None:
    pending = _pending(context)
    if pending is None:
        await _reply(update, "That prompt expired\\. Send the workout again\\.")
        return
    async with _session() as session:
        exercise = await get_exercise(session, exercise_id)
    if exercise is None:
        await _reply(update, "That exercise no longer exists\\.")
        return
    await _advance(update, context, exercise.id, exercise.canonical_name)


async def _advance(
    update: Update, context: ContextTypes.DEFAULT_TYPE, exercise_id: int, name: str
) -> None:
    pending = _pending(context)
    if pending is None:
        return
    item: AmbiguousExercise = pending["queue"].pop(0)
    pending["entries"].append((exercise_id, name, item.sets))

    if pending["queue"]:
        await _ask_next_ambiguous(update, context)
        return

    if context.chat_data is not None:
        context.chat_data.pop(PENDING_KEY, None)
    async with _session() as session:
        user = await _resolve_user(update, session)
        await _persist_and_confirm(
            update, session, user, pending["source"], pending["method"], pending["entries"]
        )


async def _confirm_undo(update: Update, choice: str) -> None:
    if choice == "no" or not choice.isdigit():
        await _reply(update, "Kept everything\\.")
        return

    async with _session() as session:
        user = await _resolve_user(update, session)
        # Re-check ownership: callback data comes from the client.
        workout = await get_owned_workout(session, user.id, int(choice))
        if workout is None:
            await _reply(update, "That workout is already gone\\.")
            return
        day = workout.performed_on
        await delete_workout(session, workout.id)
    await _reply(update, f"🗑 Deleted your *{fmt.esc(fmt.day_label(day))}* workout\\.")


# --------------------------------------------------------------------------
# errors
# --------------------------------------------------------------------------


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled error in handler", exc_info=context.error)
    if not isinstance(update, Update) or update.effective_message is None:
        return
    try:
        await update.effective_message.reply_text(
            "⚠️ Something went wrong on my end. Nothing was lost — try again in a moment."
        )
    except TelegramError:
        logger.warning("Could not deliver the error notice to the chat")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _pending(context: ContextTypes.DEFAULT_TYPE) -> dict[str, Any] | None:
    if context.chat_data is None:
        return None
    pending = context.chat_data.get(PENDING_KEY)
    if not pending or not pending.get("queue"):
        return None
    return pending


def _by_exercise(rows: list[SetRow]) -> list[tuple[str, list[ParsedSet]]]:
    grouped: dict[str, list[ParsedSet]] = {}
    for row in rows:
        grouped.setdefault(row.exercise_name, []).extend(_to_parsed([row]))
    return list(grouped.items())


def _to_parsed(rows: list[SetRow]) -> list[ParsedSet]:
    return [
        ParsedSet(
            reps=row.reps,
            weight=row.weight,
            unit=row.unit,
            rpe=row.rpe,
            is_warmup=row.is_warmup,
        )
        for row in rows
    ]


def _target_for(rows: list[SetRow], user: User) -> NextTarget | None:
    if not rows:
        return None
    points = build_session_points(rows, user.unit)
    sessions = build_session_sets(rows, user.unit)
    stalled = detect_stall(points, user.today())
    return next_target(
        sessions,
        user.unit,
        rows[-1].equipment,
        rows[-1].muscle_group,
        is_stalled=stalled,
    )


def _grouped(rows: list[SetRow]) -> list[GroupedSet]:
    return [GroupedSet(r.performed_on, r.muscle_group, r.is_warmup) for r in rows]


def _same_week(day: date, reference: date) -> bool:
    return day.isocalendar()[:2] == reference.isocalendar()[:2]


def _week_start(day: date) -> date:
    return day - timedelta(days=day.isoweekday() - 1)


def _parse_bodyweight(raw: str) -> tuple[float | None, Unit | None]:
    text = raw.lower().replace(" ", "")
    unit: Unit | None = None
    suffixes = (("kg", Unit.kg), ("kgs", Unit.kg), ("lb", Unit.lb), ("lbs", Unit.lb))
    for suffix, parsed_unit in suffixes:
        if text.endswith(suffix):
            unit = parsed_unit
            text = text[: -len(suffix)]
            break
    try:
        value = float(text)
    except ValueError:
        return None, None
    if not 20 <= value <= 1000:
        return None, None
    return value, unit
