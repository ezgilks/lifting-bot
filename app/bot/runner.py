"""Bot wiring and the polling lifecycle owned by the FastAPI lifespan."""

from __future__ import annotations

import logging

from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from app.bot import handlers
from app.config import get_settings

logger = logging.getLogger(__name__)

COMMANDS: list[tuple[str, str]] = [
    ("start", "Set up your account"),
    ("today", "What you logged today"),
    ("last", "Last 3 sessions for an exercise"),
    ("week", "This week's sessions and hard sets"),
    ("next", "Recommended next-session targets"),
    ("bw", "Log your bodyweight"),
    ("undo", "Delete one of your recent workouts"),
    ("fix", "Replace your most recent workout"),
    ("dashboard", "Open your web dashboard"),
    ("help", "Commands and input formats"),
]


def build_application() -> Application:
    application = ApplicationBuilder().token(get_settings().telegram_bot_token).build()

    application.add_handler(CommandHandler("start", handlers.start))
    application.add_handler(CommandHandler("help", handlers.help_cmd))
    application.add_handler(CommandHandler("today", handlers.today))
    application.add_handler(CommandHandler("last", handlers.last))
    application.add_handler(CommandHandler("week", handlers.week))
    application.add_handler(CommandHandler("next", handlers.next_targets))
    application.add_handler(CommandHandler("bw", handlers.bodyweight))
    application.add_handler(CommandHandler("undo", handlers.undo))
    application.add_handler(CommandHandler("fix", handlers.fix))
    application.add_handler(CommandHandler("dashboard", handlers.dashboard))
    application.add_handler(CallbackQueryHandler(handlers.on_callback))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.log_workout)
    )
    application.add_error_handler(handlers.on_error)
    return application


async def start_polling(application: Application) -> None:
    """Bring the bot up inside the already-running event loop."""
    await application.initialize()
    await application.bot.set_my_commands(COMMANDS)
    await application.start()
    if application.updater is None:  # pragma: no cover - always set by the builder
        raise RuntimeError("Application was built without an updater")
    await application.updater.start_polling(drop_pending_updates=True)
    logger.info("Telegram polling started")


async def stop_polling(application: Application) -> None:
    if application.updater is not None and application.updater.running:
        await application.updater.stop()
    if application.running:
        await application.stop()
    await application.shutdown()
    logger.info("Telegram polling stopped")
