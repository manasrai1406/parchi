"""Register: give an upload its reference number, store it, and create its `files` row.

Register never reads a file's contents and never decides whether it is a receipt.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from parchi.config import Settings
from parchi.db.enums import FileStatus
from parchi.db.models import File, UploadBatch, file_ref_seq
from parchi.ingestion.storage import ReceivedFile, Storage
from parchi.logging import bind_context, get_logger

log = get_logger(__name__)


class BatchNotFoundError(LookupError):
    pass


class BatchFullError(ValueError):
    pass


@dataclass(frozen=True)
class Registered:
    file: File


@dataclass(frozen=True)
class Duplicate:
    """Identical bytes already exist. Nothing was saved (D-006, D-015)."""

    original: File


def format_ref_no(number: int, when: datetime) -> str:
    return f"REF-{when.year:04d}-{number:06d}"


async def lock_hash(session: AsyncSession, sha256: str) -> None:
    # Serializes registrations of identical bytes until this transaction ends (D-018).
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:sha, 0))"), {"sha": sha256}
    )


async def _earliest_with_hash(session: AsyncSession, sha256: str) -> File | None:
    result = await session.execute(
        select(File).where(File.sha256 == sha256).order_by(File.id).limit(1)
    )
    return result.scalar_one_or_none()


async def _check_batch_has_room(session: AsyncSession, batch_id: int, max_files: int) -> None:
    batch = await session.get(UploadBatch, batch_id, with_for_update=True)
    if batch is None:
        raise BatchNotFoundError(batch_id)
    count = await session.scalar(
        select(func.count()).select_from(File).where(File.batch_id == batch_id)
    )
    if (count or 0) >= max_files:
        raise BatchFullError(f"A batch holds at most {max_files} files. Start a new batch.")


async def register(
    session: AsyncSession,
    storage: Storage,
    settings: Settings,
    *,
    batch_id: int,
    display_name: str,
    ext: str,
    received: ReceivedFile,
    confirm_duplicate: bool,
) -> Registered | Duplicate:
    """Register one received upload inside a single transaction.

    The temporary upload is always consumed: stored, or discarded.
    """
    newly_written_path: str | None = None
    try:
        async with session.begin():
            await _check_batch_has_room(session, batch_id, settings.max_files_per_batch)
            await lock_hash(session, received.sha256)

            original = await _earliest_with_hash(session, received.sha256)
            if original is not None and not confirm_duplicate:
                log.info("file.duplicate_detected", duplicate_of_id=original.id)
                received.discard()
                return Duplicate(original=original)

            storage_path, newly_written = storage.store(received, ext)
            if newly_written:
                newly_written_path = storage_path

            number = await session.scalar(select(file_ref_seq.next_value()))
            now = datetime.now(settings.tz)
            file = File(
                ref_no=format_ref_no(number, now),
                batch_id=batch_id,
                original_name=display_name,
                sha256=received.sha256,
                size_bytes=received.size_bytes,
                storage_path=storage_path,
                status=FileStatus.PENDING,
                duplicate_of_id=original.id if original is not None else None,
            )
            session.add(file)
            await session.flush()
            bind_context(file_id=file.id, ref_no=file.ref_no)
            log.info(
                "file.registered",
                size_bytes=file.size_bytes,
                duplicate_of_id=file.duplicate_of_id,
            )
        # Committed: from here on the stored bytes belong to the new row.
        newly_written_path = None
        await session.refresh(file)
        return Registered(file=file)
    except BaseException:
        received.discard()
        if newly_written_path is not None and not await _path_in_use(session, newly_written_path):
            storage.remove(newly_written_path)
        raise


async def _path_in_use(session: AsyncSession, storage_path: str) -> bool:
    try:
        return bool(
            await session.scalar(
                select(select(File.id).where(File.storage_path == storage_path).exists())
            )
        )
    except Exception:
        # If we cannot tell, keep the bytes: an orphan is safer than a missing original.
        return True
