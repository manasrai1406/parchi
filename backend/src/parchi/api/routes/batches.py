"""Upload batches (D-017): create a batch, then send each file on its own."""

from typing import Annotated

from fastapi import APIRouter, Form, Request, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from starlette.concurrency import run_in_threadpool

from parchi.api.deps import SessionDep, SettingsDep, StorageDep
from parchi.api.errors import AppError, ErrorResponse
from parchi.db.models import File, UploadBatch
from parchi.db.repositories import get_file
from parchi.ingestion.names import (
    UnsafeNameError,
    UnsupportedTypeError,
    clean_display_name,
    extension_of,
)
from parchi.ingestion.registry import (
    BatchFullError,
    BatchNotFoundError,
    Duplicate,
    register,
)
from parchi.ingestion.storage import FileTooLargeError
from parchi.logging import bind_context, get_logger
from parchi.schemas.api import (
    BatchDetail,
    BatchOut,
    DuplicateResult,
    FileRef,
    FileSummary,
    RegisteredResult,
    UploadResult,
)

router = APIRouter(prefix="/batches", tags=["batches"])
log = get_logger(__name__)

# Allowance for multipart framing on top of the file itself.
MULTIPART_OVERHEAD_BYTES = 64 * 1024


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_batch(session: SessionDep) -> BatchOut:
    async with session.begin():
        batch = UploadBatch()
        session.add(batch)
    bind_context(batch_id=batch.id)
    log.info("batch.created")
    return BatchOut.model_validate(batch)


@router.get("/{batch_id}", responses={404: {"model": ErrorResponse}})
async def get_batch(batch_id: int, session: SessionDep) -> BatchDetail:
    batch = await session.get(UploadBatch, batch_id)
    if batch is None:
        raise AppError(404, "batch_not_found", "Batch not found.")
    result = await session.execute(
        select(File)
        .where(File.batch_id == batch_id)
        .options(selectinload(File.duplicate_of))
        .order_by(File.id)
    )
    files = [FileSummary.model_validate(file) for file in result.scalars()]
    return BatchDetail(id=batch.id, created_at=batch.created_at, files=files)


@router.post(
    "/{batch_id}/files",
    status_code=status.HTTP_201_CREATED,
    responses={
        200: {"model": DuplicateResult, "description": "Identical file exists; nothing saved"},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        413: {"model": ErrorResponse},
        415: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def upload_file(
    batch_id: int,
    file: UploadFile,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    storage: StorageDep,
    confirm_duplicate: Annotated[bool, Form()] = False,
) -> UploadResult:
    """Register one file. An identical file is not saved unless confirm_duplicate is true."""
    bind_context(batch_id=batch_id)
    max_bytes = settings.max_upload_bytes
    too_large = AppError(
        413, "file_too_large", f"Files can be at most {settings.max_upload_mb} MB."
    )

    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > max_bytes + MULTIPART_OVERHEAD_BYTES:
        raise too_large

    try:
        name = clean_display_name(file.filename)
        ext = extension_of(name)
    except UnsafeNameError as exc:
        raise AppError(422, "invalid_name", str(exc)) from exc
    except UnsupportedTypeError as exc:
        raise AppError(415, "unsupported_type", str(exc)) from exc

    try:
        received = await run_in_threadpool(storage.receive, file.file, max_bytes)
    except FileTooLargeError as exc:
        raise too_large from exc

    try:
        outcome = await register(
            session,
            storage,
            settings,
            batch_id=batch_id,
            display_name=name,
            ext=ext,
            received=received,
            confirm_duplicate=confirm_duplicate,
        )
    except BatchNotFoundError as exc:
        raise AppError(404, "batch_not_found", "Batch not found.") from exc
    except BatchFullError as exc:
        raise AppError(409, "batch_full", str(exc)) from exc

    if isinstance(outcome, Duplicate):
        response.status_code = status.HTTP_200_OK
        return DuplicateResult(duplicate_of=FileRef.model_validate(outcome.original))

    file = await get_file(session, outcome.file.id)
    return RegisteredResult(file=FileSummary.model_validate(file))
