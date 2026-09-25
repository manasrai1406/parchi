"""Files, addressed by id or reference number, never by storage path (hard rule 4)."""

from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse

from parchi.api.deps import SessionDep, StorageDep
from parchi.api.errors import AppError, ErrorResponse
from parchi.db.enums import FileStatus
from parchi.db.models import File
from parchi.db.repositories import get_file, list_files
from parchi.logging import bind_context, get_logger
from parchi.schemas.api import FilePage, FileSummary

router = APIRouter(prefix="/files", tags=["files"])
log = get_logger(__name__)

MEDIA_TYPES = {
    "pdf": "application/pdf",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "heic": "image/heic",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xls": "application/vnd.ms-excel",
    "csv": "text/csv",
}

NOT_FOUND = {404: {"model": ErrorResponse}}


async def _require_file(session: SessionDep, file_key: str) -> File:
    file = await get_file(session, file_key)
    if file is None:
        raise AppError(404, "file_not_found", "File not found.")
    bind_context(file_id=file.id, ref_no=file.ref_no)
    return file


@router.get("")
async def get_files(
    session: SessionDep,
    status: FileStatus | None = None,
    q: Annotated[str | None, Query(max_length=100, description="Name or reference")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> FilePage:
    files, total = await list_files(
        session, status=status, search=(q or "").strip() or None, page=page, page_size=page_size
    )
    return FilePage(
        items=[FileSummary.model_validate(file) for file in files],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{file_key}", responses=NOT_FOUND)
async def get_one_file(file_key: str, session: SessionDep) -> FileSummary:
    """One file, by id or reference number."""
    return FileSummary.model_validate(await _require_file(session, file_key))


@router.get(
    "/{file_key}/download",
    response_class=FileResponse,
    responses={**NOT_FOUND, 200: {"content": {"application/octet-stream": {}}}},
)
async def download_file(file_key: str, session: SessionDep, storage: StorageDep) -> FileResponse:
    """The original file, under its original name."""
    file = await _require_file(session, file_key)
    path = storage.absolute_path(file.storage_path)
    if not path.is_file():
        log.error("file.missing_on_disk")
        raise AppError(410, "file_missing", "The stored file is missing. Check the uploads folder.")
    ext = file.storage_path.rsplit(".", 1)[-1]
    log.info("file.downloaded")
    return FileResponse(
        path,
        media_type=MEDIA_TYPES.get(ext, "application/octet-stream"),
        filename=file.original_name,
        content_disposition_type="attachment",
    )
