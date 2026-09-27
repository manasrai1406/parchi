"""Logging in and managing accounts (D-043, D-045)."""

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from parchi.auth import passwords
from parchi.auth.sessions import now
from parchi.db.enums import UserRole
from parchi.db.models import User

MAX_FAILED_LOGINS = 5
LOCK_FOR = timedelta(minutes=15)


class LoginError(Exception):
    """Safe to show: it never says whether the username exists."""


def normalize_username(username: str) -> str:
    return username.strip().lower()


async def find_by_username(session: AsyncSession, username: str) -> User | None:
    return await session.scalar(select(User).where(User.username == normalize_username(username)))


async def authenticate(session: AsyncSession, username: str, password: str) -> User:
    """The user these details belong to, or LoginError. Commits the attempt's outcome."""
    user = await find_by_username(session, username)
    moment = now()
    if user is None or not user.active:
        passwords.waste_time(password)
        raise LoginError("Wrong username or password.")
    if user.locked_until is not None and user.locked_until > moment:
        passwords.waste_time(password)
        raise LoginError("Too many wrong passwords. Try again in 15 minutes.")
    if not passwords.verify_password(user.password_hash, password):
        user.failed_logins += 1
        if user.failed_logins >= MAX_FAILED_LOGINS:
            user.failed_logins = 0
            user.locked_until = moment + LOCK_FOR
        await session.commit()
        raise LoginError("Wrong username or password.")
    if passwords.needs_rehash(user.password_hash):
        user.password_hash = passwords.hash_password(password)
    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = moment
    return user


def set_password(user: User, password: str, *, temporary: bool) -> None:
    """A temporary password (new account or reset) must be changed at the next login."""
    user.password_hash = passwords.hash_password(password)
    user.must_change_password = temporary
    user.failed_logins = 0
    user.locked_until = None


async def active_admins(session: AsyncSession) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(User)
        .where(User.role == UserRole.ADMIN, User.active.is_(True))
    )
    return count or 0
