"""Delete a file and everything that belongs to it (D-019)."""

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from parchi.db.enums import FileStatus
from parchi.db.models import ExtractionRun, File, Flag, Receipt
from parchi.ingestion.registry import lock_hash
from parchi.ingestion.storage import Storage
from parchi.logging import get_logger

log = get_logger(__name__)

BUSY_STATUSES = (FileStatus.PROCESSING, FileStatus.AI_PROCESSING)


class FileNotFoundInDbError(LookupError):
    pass


class FileBusyError(ValueError):
    pass


@dataclass(frozen=True)
class Deleted:
    file_id: int
    ref_no: str
    new_original_id: int | None


async def delete_file(session: AsyncSession, storage: Storage, file_id: int) -> Deleted:
    """Delete in one transaction. Stored bytes are set aside first and only erased after
    the commit, so a failed delete leaves the file exactly as it was."""
    aside: Path | None = None
    storage_path: str | None = None
    try:
        async with session.begin():
            sha256 = await session.scalar(select(File.sha256).where(File.id == file_id))
            if sha256 is None:
                raise FileNotFoundInDbError(file_id)
            # The hash lock first, then the row: the same order as Register, so the two
            # cannot deadlock. It also stops anyone reusing these bytes meanwhile (D-018).
            await lock_hash(session, sha256)
            file = await session.get(File, file_id, with_for_update=True, populate_existing=True)
            if file is None:
                raise FileNotFoundInDbError(file_id)
            if file.status in BUSY_STATUSES:
                raise FileBusyError("This file is being processed. Try again when it finishes.")

            new_original_id = await _promote_earliest_copy(session, file.id)

            await session.execute(delete(Flag).where(Flag.file_id == file.id))
            await session.execute(delete(Receipt).where(Receipt.file_id == file.id))
            await session.execute(delete(ExtractionRun).where(ExtractionRun.file_id == file.id))
            ref_no, storage_path = file.ref_no, file.storage_path
            await session.execute(delete(File).where(File.id == file.id))

            still_used = await session.scalar(
                select(select(File.id).where(File.storage_path == storage_path).exists())
            )
            if not still_used:
                aside = storage.set_aside(storage_path)
            log.info(
                "file.deleted",
                deleted_file_id=file_id,
                new_original_id=new_original_id,
                bytes_removed=not still_used,
            )
    except BaseException:
        if aside is not None and storage_path is not None:
            storage.put_back(aside, storage_path)
        raise

    if aside is not None:
        aside.unlink(missing_ok=True)
    return Deleted(file_id=file_id, ref_no=ref_no, new_original_id=new_original_id)


async def _promote_earliest_copy(session: AsyncSession, file_id: int) -> int | None:
    """Copies of the deleted file now point at the earliest copy, which becomes the original."""
    copies = (
        await session.scalars(
            select(File.id).where(File.duplicate_of_id == file_id).order_by(File.id)
        )
    ).all()
    if not copies:
        return None
    new_original, *rest = copies
    await session.execute(update(File).where(File.id == new_original).values(duplicate_of_id=None))
    if rest:
        await session.execute(
            update(File).where(File.id.in_(rest)).values(duplicate_of_id=new_original)
        )
    return new_original
