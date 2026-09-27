"""Who is asking, and whether their role allows it (D-043, D-044).

The checks use their own database session, so a route's own transaction is untouched.
"""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from parchi.api.errors import AppError
from parchi.auth import sessions
from parchi.config import get_settings
from parchi.db.enums import UserRole
from parchi.db.session import get_sessionmaker
from parchi.logging import bind_context

RANK = {UserRole.VIEWER: 0, UserRole.REVIEWER: 1, UserRole.ADMIN: 2}


@dataclass(frozen=True)
class CurrentUser:
    id: int
    username: str
    display_name: str
    role: UserRole
    must_change_password: bool

    def can(self, role: UserRole) -> bool:
        return RANK[self.role] >= RANK[role]


async def current_user(request: Request) -> CurrentUser:
    token = request.cookies.get(sessions.COOKIE)
    if not token:
        raise AppError(401, "not_logged_in", "Please log in.")
    async with get_sessionmaker()() as session:
        user = await sessions.find_user(session, token, get_settings().session_days)
    if user is None:
        raise AppError(401, "not_logged_in", "Your session has ended. Please log in again.")
    bind_context(user_id=user.id)
    return CurrentUser(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        role=UserRole(user.role),
        must_change_password=user.must_change_password,
    )


def _require(role: UserRole, *, before_password_change: bool = False):
    async def check(user: Annotated[CurrentUser, Depends(current_user)]) -> CurrentUser:
        if user.must_change_password and not before_password_change:
            raise AppError(403, "password_change_required", "Choose a new password to continue.")
        if not user.can(role):
            raise AppError(403, "forbidden", "Your role does not allow this.")
        return user

    check.__name__ = f"require_{role.value}"
    return check


# One function per level, made once, so FastAPI runs each check only once per request.
require_viewer = _require(UserRole.VIEWER)
require_reviewer = _require(UserRole.REVIEWER)
require_admin = _require(UserRole.ADMIN)
# Logging out and changing a temporary password must work before the password is changed.
require_login = _require(UserRole.VIEWER, before_password_change=True)

Viewer = Annotated[CurrentUser, Depends(require_viewer)]
Reviewer = Annotated[CurrentUser, Depends(require_reviewer)]
Admin = Annotated[CurrentUser, Depends(require_admin)]
LoggedIn = Annotated[CurrentUser, Depends(require_login)]
