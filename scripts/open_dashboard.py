#!/usr/bin/env python
"""Mint a dashboard magic link and open it, without going through Telegram.

    .venv/bin/python scripts/open_dashboard.py            # the only user
    .venv/bin/python scripts/open_dashboard.py --chat-id 7330212125
    .venv/bin/python scripts/open_dashboard.py --print    # just print the URL

Reads the same .env the app does, so the link is signed with the same secret
and points at the same PUBLIC_BASE_URL.
"""

from __future__ import annotations

import argparse
import asyncio
import pathlib
import sys
import webbrowser

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def load_env() -> None:
    """Populate os.environ from .env before app.config reads it."""
    import os

    env_file = REPO_ROOT / ".env"
    if not env_file.is_file():
        raise SystemExit(f"No .env at {env_file}. Copy .env.example and fill it in.")
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


async def resolve_user_id(chat_id: int | None) -> int:
    from sqlalchemy import select

    from app.db import dispose_engine, get_session_factory
    from app.models import User

    try:
        async with get_session_factory()() as session:
            if chat_id is not None:
                user = await session.scalar(
                    select(User).where(User.telegram_chat_id == chat_id)
                )
                if user is None:
                    raise SystemExit(f"No user with telegram_chat_id {chat_id}")
                return user.id

            users = list(await session.scalars(select(User).order_by(User.id)))
            if not users:
                raise SystemExit("No users yet — send /start to the bot first.")
            if len(users) > 1:
                listing = "\n".join(
                    f"  --chat-id {u.telegram_chat_id}  ({u.display_name or 'unnamed'})"
                    for u in users
                )
                raise SystemExit(f"More than one user. Pick one:\n{listing}")
            return users[0].id
    finally:
        await dispose_engine()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chat-id", type=int, default=None)
    parser.add_argument(
        "--print", action="store_true", dest="print_only", help="print without opening"
    )
    args = parser.parse_args()

    load_env()
    from app.api.auth import dashboard_link

    url = dashboard_link(asyncio.run(resolve_user_id(args.chat_id)))
    print(url)
    if not args.print_only:
        webbrowser.open(url)


if __name__ == "__main__":
    main()
