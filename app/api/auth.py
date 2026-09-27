"""Magic-link auth: the bot issues a JWT, the dashboard presents it as a bearer."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.models import User
from app.queries import get_user_by_id

ALGORITHM = "HS256"
TOKEN_TTL = timedelta(hours=24)

_bearer = HTTPBearer(auto_error=False)


def issue_token(user_id: int) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + TOKEN_TTL).timestamp()),
    }
    return jwt.encode(payload, get_settings().app_secret, algorithm=ALGORITHM)


def dashboard_link(user_id: int) -> str:
    return f"{get_settings().public_base_url}/?t={issue_token(user_id)}"


def decode_token(token: str) -> int:
    try:
        payload = jwt.decode(token, get_settings().app_secret, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Link expired, send /dashboard again"
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from exc

    subject = payload.get("sub")
    if subject is None or not str(subject).isdigit():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token subject")
    return int(subject)


async def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    if credentials is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = await get_user_by_id(session, decode_token(credentials.credentials))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown user")
    return user


CurrentUser = Annotated[User, Depends(current_user)]
