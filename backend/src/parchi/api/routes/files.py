"""Files, addressed by id or reference number, never by storage path (hard rule 4)."""

import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Query, Response
from fastapi import status as http_status
from fastapi.responses import FileResponse
from sqlalchemy import select
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from parchi.api.deps import SessionDep, SettingsDep, StorageDep
from parchi.api.errors import AppError, ErrorResponse
from parchi.db.enums import FileStatus
from parchi.db.models import File
from parchi.db.repositories import (
    attention_condition,
    file_counts,
    get_file,
    get_file_detail,
    list_files,
)
from parchi.ingestion.deletion import FileBusyError, FileNotFoundInDbError, delete_file
from parchi.logging import bind_context, get_logger
from parchi.review.actions import UnknownCategoryError, reject_file, save_manual
from parchi.review.report import build_report
from parchi.review.views import file_detail
from parchi.schemas.api import (
    FileCounts,
    FileDetail,
    FilePage,
    FileSummary,
    ManualEdit,
    RejectIn,
)
from parchi.validation import rules

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
# Types a browser can show inside the Review page; others always download.
INLINE_TYPES = {"pdf", "jpg", "jpeg", "png", "webp"}
# The "all flagged" zip is capped so it stays a reasonable download.
MAX_FILES_IN_ZIP = 200

NOT_FOUND = {404: {"model": ErrorResponse}}
ERRORS = {**NOT_FOUND, 409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}}
PDF = {200: {"content": {"application/pdf": {}}}}


async def _require_file(session: SessionDep, file_key: str) -> File:
    file = await get_file(session, file_key)
    if file is None:
        raise AppError(404, "file_not_found", "File not found.")
    bind_context(file_id=file.id, ref_no=file.ref_no)
    return file


async def _require_detail(session: SessionDep, file_key: str) -> FileDetail:
    file = await get_file_detail(session, file_key)
    if file is None:
        raise AppError(404, "file_not_found", "File not found.")
    bind_context(file_id=file.id, ref_no=file.ref_no)
    return file_detail(file)


@router.get("")
async def get_files(
    session: SessionDep,
    status: FileStatus | None = None,
    q: Annotated[str | None, Query(max_length=100, description="Name or reference")] = None,
    attention: Annotated[
        bool, Query(description="Only files a person should look at (the Review queue)")
    ] = False,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> FilePage:
    files, total = await list_files(
        session,
        status=status,
        search=(q or "").strip() or None,
        attention=attention,
        page=page,
        page_size=page_size,
    )
    return FilePage(
        items=[FileSummary.model_validate(file) for file in files],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/summary")
async def get_summary(session: SessionDep) -> FileCounts:
    """Counts per status, for the summary cards, chips and sidebar badges."""
    return FileCounts.model_validate(await file_counts(session))


@router.get(
    "/error-reports.zip",
    response_class=FileResponse,
    responses={200: {"content": {"application/zip": {}}}},
)
async def all_error_reports(session: SessionDep, storage: StorageDep) -> FileResponse:
    """The originals of every file needing attention, plus one combined PDF report."""
    ids = (
        await session.scalars(
            select(File.id).where(attention_condition()).order_by(File.id).limit(MAX_FILES_IN_ZIP)
        )
    ).all()
    details = [file_detail(file) for i in ids if (file := await get_file_detail(session, i))]
    stored = {d.id: (await get_file(session, d.id)) for d in details}
    report = await run_in_threadpool(build_report, details)

    def write_zip() -> Path:
        storage.ensure_dirs()
        handle = tempfile.NamedTemporaryFile(
            dir=storage.tmp_dir, prefix="report-", suffix=".zip", delete=False
        )
        with handle, zipfile.ZipFile(handle, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("error-report.pdf", report)
            for detail in details:
                file = stored[detail.id]
                path = storage.absolute_path(file.storage_path) if file else None
                if path and path.is_file():
                    archive.write(path, f"originals/{detail.ref_no} - {detail.original_name}")
        return Path(handle.name)

    zip_path = await run_in_threadpool(write_zip)
    log.info("files.error_reports_zipped", files=len(details))
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=f"parchi-error-reports-{datetime.now():%Y%m%d-%H%M}.zip",
        background=BackgroundTask(zip_path.unlink, missing_ok=True),
    )


@router.get("/{file_key}", responses=NOT_FOUND)
async def get_one_file(file_key: str, session: SessionDep) -> FileDetail:
    """One file, by id or reference number, with its receipts, flags and runs."""
    return await _require_detail(session, file_key)


@router.get(
    "/{file_key}/download",
    response_class=FileResponse,
    responses={**NOT_FOUND, 200: {"content": {"application/octet-stream": {}}}},
)
async def download_file(
    file_key: str,
    session: SessionDep,
    storage: StorageDep,
    inline: Annotated[bool, Query(description="Show in the browser (PDFs and images)")] = False,
) -> FileResponse:
    """The original file, under its original name."""
    file = await _require_file(session, file_key)
    path = storage.absolute_path(file.storage_path)
    if not path.is_file():
        log.error("file.missing_on_disk")
        raise AppError(410, "file_missing", "The stored file is missing. Check the uploads folder.")
    ext = file.storage_path.rsplit(".", 1)[-1]
    show_inline = inline and ext in INLINE_TYPES
    log.info("file.downloaded", inline=show_inline)
    return FileResponse(
        path,
        media_type=MEDIA_TYPES.get(ext, "application/octet-stream"),
        filename=file.original_name,
        content_disposition_type="inline" if show_inline else "attachment",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.get("/{file_key}/error-report", response_class=Response, responses={**NOT_FOUND, **PDF})
async def error_report(file_key: str, session: SessionDep) -> Response:
    """A PDF with the file's problems and what each reader found (D-031)."""
    detail = await _require_detail(session, file_key)
    pdf = await run_in_threadpool(build_report, [detail])
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{detail.ref_no}-error-report.pdf"'},
    )


@router.put("/{file_key}/receipts", responses=ERRORS)
async def save_receipts(
    file_key: str, body: ManualEdit, session: SessionDep, settings: SettingsDep
) -> FileDetail:
    """Save a person's edits as the accepted result; the file becomes resolved (D-030)."""
    file = await _require_file(session, file_key)
    file_id = file.id
    await session.rollback()
    try:
        await save_manual(
            session,
            file_id,
            body.receipts,
            user=settings.local_user_name,
            today=rules.current_date(),
        )
    except FileNotFoundInDbError as exc:
        raise AppError(404, "file_not_found", "File not found.") from exc
    except FileBusyError as exc:
        raise AppError(409, "file_busy", str(exc)) from exc
    except UnknownCategoryError as exc:
        raise AppError(422, "unknown_category", "That category no longer exists.") from exc
    return await _require_detail(session, file_key)


@router.post("/{file_key}/reject", responses=ERRORS)
async def reject(
    file_key: str, body: RejectIn, session: SessionDep, settings: SettingsDep
) -> FileDetail:
    """Not a receipt, or a bad scan (D-030 item 4)."""
    file = await _require_file(session, file_key)
    file_id = file.id
    await session.rollback()
    try:
        await reject_file(session, file_id, body.reason, user=settings.local_user_name)
    except FileNotFoundInDbError as exc:
        raise AppError(404, "file_not_found", "File not found.") from exc
    except FileBusyError as exc:
        raise AppError(409, "file_busy", str(exc)) from exc
    return await _require_detail(session, file_key)


@router.delete(
    "/{file_key}",
    status_code=http_status.HTTP_204_NO_CONTENT,
    responses={**NOT_FOUND, 409: {"model": ErrorResponse}},
)
async def remove_file(file_key: str, session: SessionDep, storage: StorageDep) -> Response:
    """Delete a file with its runs, receipts and flags (D-019). Not while it is processing."""
    file = await _require_file(session, file_key)
    file_id = file.id
    await session.rollback()  # end the read above; delete_file runs its own transaction
    try:
        await delete_file(session, storage, file_id)
    except FileNotFoundInDbError as exc:
        raise AppError(404, "file_not_found", "File not found.") from exc
    except FileBusyError as exc:
        raise AppError(409, "file_busy", str(exc)) from exc
    return Response(status_code=http_status.HTTP_204_NO_CONTENT)
