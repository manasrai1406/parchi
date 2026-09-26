"""Flags: problems a person looks at and marks as OK (D-030 item 3)."""

from fastapi import APIRouter

from parchi.api.deps import SessionDep, SettingsDep
from parchi.api.errors import AppError, ErrorResponse
from parchi.review.actions import FlagNotFoundError, resolve_flag
from parchi.schemas.api import FlagOut

router = APIRouter(prefix="/flags", tags=["flags"])


@router.post("/{flag_id}/resolve", responses={404: {"model": ErrorResponse}})
async def resolve(flag_id: int, session: SessionDep, settings: SettingsDep) -> FlagOut:
    try:
        flag = await resolve_flag(session, flag_id, user=settings.local_user_name)
    except FlagNotFoundError as exc:
        raise AppError(404, "flag_not_found", "Flag not found.") from exc
    return FlagOut.model_validate(flag)
