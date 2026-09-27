"""Managing accounts: admins only (D-045)."""

from fastapi import APIRouter
from fastapi import status as http_status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from parchi.api.deps import SessionDep
from parchi.api.errors import AppError, ErrorResponse
from parchi.auth import accounts, sessions
from parchi.auth.deps import Admin
from parchi.db.enums import UserRole
from parchi.db.models import User
from parchi.logging import get_logger
from parchi.schemas.api import PasswordResetIn, UserCreateIn, UserOut, UserUpdateIn

router = APIRouter(prefix="/users", tags=["users"])
log = get_logger(__name__)

ERRORS = {404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}}


async def _get(session: SessionDep, user_id: int) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise AppError(404, "user_not_found", "User not found.")
    return user


def _taken(username: str) -> AppError:
    return AppError(409, "username_taken", f'The username "{username}" is already taken.')


@router.get("")
async def list_users(session: SessionDep, _: Admin) -> list[UserOut]:
    users = await session.scalars(select(User).order_by(User.username))
    return [UserOut.model_validate(user) for user in users]


@router.post("", status_code=http_status.HTTP_201_CREATED, responses=ERRORS)
async def create_user(body: UserCreateIn, session: SessionDep, admin: Admin) -> UserOut:
    if await accounts.find_by_username(session, body.username) is not None:
        raise _taken(body.username)
    user = User(username=body.username, display_name=body.display_name, role=body.role)
    accounts.set_password(user, body.temporary_password, temporary=True)
    session.add(user)
    try:
        await session.commit()
    except IntegrityError as exc:  # created by someone else a moment ago
        raise _taken(body.username) from exc
    log.info("users.created", new_user_id=user.id, role=user.role, by=admin.id)
    return UserOut.model_validate(user)


@router.patch("/{user_id}", responses=ERRORS)
async def update_user(
    user_id: int, body: UserUpdateIn, session: SessionDep, admin: Admin
) -> UserOut:
    user = await _get(session, user_id)
    if user.id == admin.id and (
        (body.role is not None and body.role != UserRole.ADMIN) or body.active is False
    ):
        raise AppError(409, "own_account", "You cannot demote or deactivate your own account.")
    if body.display_name is not None:
        user.display_name = body.display_name
    if body.role is not None:
        user.role = body.role
    if body.active is not None:
        user.active = body.active
        if not body.active:
            await sessions.end_all(session, user.id)
    await session.commit()
    log.info("users.updated", target_user_id=user.id, fields=sorted(body.model_fields_set))
    return UserOut.model_validate(user)


@router.post("/{user_id}/password", responses=ERRORS)
async def reset_password(
    user_id: int, body: PasswordResetIn, session: SessionDep, admin: Admin
) -> UserOut:
    """Set a temporary password; the user must choose a new one at the next login."""
    user = await _get(session, user_id)
    accounts.set_password(user, body.temporary_password, temporary=True)
    await sessions.end_all(session, user.id)
    await session.commit()
    log.info("users.password_reset", target_user_id=user.id, by=admin.id)
    return UserOut.model_validate(user)
