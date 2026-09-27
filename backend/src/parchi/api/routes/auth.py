"""Logging in and out, and changing one's own password (D-043)."""

from fastapi import APIRouter, Request, Response
from fastapi import status as http_status

from parchi.api.deps import SessionDep, SettingsDep
from parchi.api.errors import AppError, ErrorResponse
from parchi.auth import accounts, passwords, sessions
from parchi.auth.deps import LoggedIn
from parchi.config import Settings
from parchi.db.models import User
from parchi.logging import bind_context, get_logger
from parchi.schemas.api import LoginIn, MeOut, PasswordChangeIn

router = APIRouter(prefix="/auth", tags=["auth"])
log = get_logger(__name__)


def _set_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        sessions.COOKIE,
        token,
        max_age=settings.session_days * 24 * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/",
    )


@router.post("/login", responses={401: {"model": ErrorResponse}})
async def login(
    body: LoginIn, response: Response, session: SessionDep, settings: SettingsDep
) -> MeOut:
    try:
        user = await accounts.authenticate(session, body.username, body.password)
    except accounts.LoginError as exc:
        log.info("auth.login_refused")
        raise AppError(401, "login_failed", str(exc)) from exc
    token = await sessions.start(session, user.id, settings.session_days)
    await session.commit()
    bind_context(user_id=user.id)
    log.info("auth.logged_in")
    _set_cookie(response, token, settings)
    return MeOut.model_validate(user)


@router.post("/logout", status_code=http_status.HTTP_204_NO_CONTENT)
async def logout(request: Request, session: SessionDep, _: LoggedIn) -> Response:
    token = request.cookies.get(sessions.COOKIE)
    if token:
        await sessions.end(session, token)
        await session.commit()
    log.info("auth.logged_out")
    response = Response(status_code=http_status.HTTP_204_NO_CONTENT)
    response.delete_cookie(sessions.COOKIE, path="/", samesite="strict", httponly=True)
    return response


@router.get("/me")
async def me(user: LoggedIn) -> MeOut:
    """Who is logged in. 401 when nobody is."""
    return MeOut(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        must_change_password=user.must_change_password,
    )


@router.put("/password", responses={400: {"model": ErrorResponse}})
async def change_password(
    body: PasswordChangeIn, request: Request, session: SessionDep, user: LoggedIn
) -> MeOut:
    """Change one's own password. Other sessions of this user are ended."""
    row = await session.get(User, user.id)
    if row is None or not passwords.verify_password(row.password_hash, body.current_password):
        raise AppError(400, "wrong_password", "The current password is not right.")
    if body.new_password == body.current_password:
        raise AppError(400, "same_password", "Choose a password you have not just used.")
    if body.new_password.lower() == row.username:
        raise AppError(400, "weak_password", "The password cannot be your username.")
    accounts.set_password(row, body.new_password, temporary=False)
    await sessions.end_all(session, row.id, keep_token=request.cookies.get(sessions.COOKIE))
    await session.commit()
    log.info("auth.password_changed")
    return MeOut.model_validate(row)
