"""Login sessions: a random token in the browser's cookie, its SHA-256 in the database."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from parchi.db.models import User, UserSession

COOKIE = "parchi_session"
# A session's expiry moves forward when it is used, at most this often.
TOUCH_EVERY = timedelta(hours=1)


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def now() -> datetime:
    return datetime.now(UTC)


async def start(session: AsyncSession, user_id: int, days: int) -> str:
    """A new session for a user; returns the token for the cookie. The caller commits."""
    token = secrets.token_urlsafe(32)
    moment = now()
    session.add(
        UserSession(
            token_hash=digest(token),
            user_id=user_id,
            expires_at=moment + timedelta(days=days),
            last_seen_at=moment,
        )
    )
    return token


async def find_user(session: AsyncSession, token: str, days: int) -> User | None:
    """The active user a live session belongs to, extending the session while in use."""
    moment = now()
    row = (
        await session.execute(
            select(UserSession, User)
            .join(User, User.id == UserSession.user_id)
            .where(
                UserSession.token_hash == digest(token),
                UserSession.expires_at > moment,
                User.active.is_(True),
            )
        )
    ).one_or_none()
    if row is None:
        return None
    user_session, user = row
    if moment - user_session.last_seen_at > TOUCH_EVERY:
        user_session.last_seen_at = moment
        user_session.expires_at = moment + timedelta(days=days)
        await session.commit()
    return user


async def end(session: AsyncSession, token: str) -> None:
    await session.execute(delete(UserSession).where(UserSession.token_hash == digest(token)))


async def end_all(session: AsyncSession, user_id: int, keep_token: str | None = None) -> None:
    """End a user's sessions, except the one making the request if given."""
    query = delete(UserSession).where(UserSession.user_id == user_id)
    if keep_token is not None:
        query = query.where(UserSession.token_hash != digest(keep_token))
    await session.execute(query)


async def end_expired(session: AsyncSession) -> int:
    result = await session.execute(delete(UserSession).where(UserSession.expires_at <= now()))
    return result.rowcount or 0
