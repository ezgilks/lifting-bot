"""FastAPI application: REST API, static dashboard, and the bot polling task."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router as api_router
from app.bot.runner import build_application, start_polling, stop_polling
from app.config import get_settings
from app.db import Base, dispose_engine, get_engine, get_session_factory
from app.seed import seed_exercises

logger = logging.getLogger(__name__)

FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    # httpx logs every Telegram long-poll at INFO, which drowns everything else.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    engine = get_engine()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with get_session_factory()() as session:
        await seed_exercises(session)

    application = build_application()
    await start_polling(application)
    app.state.telegram = application
    try:
        yield
    finally:
        await stop_polling(application)
        await dispose_engine()


app = FastAPI(title="Lifting Bot", version="1.0.0", lifespan=lifespan)
app.include_router(api_router)


@app.get("/healthz", include_in_schema=False)
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


def _mount_frontend(application: FastAPI) -> None:
    index = FRONTEND_DIST / "index.html"
    if not index.is_file():
        logger.warning(
            "No frontend build at %s. Run `npm run build` in frontend/ "
            "or use the Vite dev server.",
            FRONTEND_DIST,
        )
        return

    assets = FRONTEND_DIST / "assets"
    if assets.is_dir():
        application.mount("/assets", StaticFiles(directory=assets), name="assets")

    @application.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        """Serve built files directly, and hand every other route to the SPA."""
        if path:
            candidate = (FRONTEND_DIST / path).resolve()
            if FRONTEND_DIST in candidate.parents and candidate.is_file():
                return FileResponse(candidate)
            if path.startswith("api/"):
                raise HTTPException(404, "Unknown endpoint")
        return FileResponse(index)


_mount_frontend(app)
