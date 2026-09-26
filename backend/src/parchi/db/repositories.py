"""Reusable queries."""

import re

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from parchi.db.enums import FileStatus
from parchi.db.models import File, Receipt

_REF_NO = re.compile(r"^REF-\d{4}-\d{6,}$")


def _files() -> Select[tuple[File]]:
    return select(File).options(selectinload(File.duplicate_of))


async def get_file(session: AsyncSession, key: str | int) -> File | None:
    """A file by id or reference number, with the file it duplicates loaded."""
    if isinstance(key, int) or key.isdigit():
        query = _files().where(File.id == int(key))
    elif _REF_NO.match(key):
        query = _files().where(File.ref_no == key)
    else:
        return None
    result = await session.execute(query.execution_options(populate_existing=True))
    return result.scalar_one_or_none()


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def list_files(
    session: AsyncSession,
    *,
    status: FileStatus | None,
    search: str | None,
    attention: bool = False,
    page: int,
    page_size: int,
) -> tuple[list[File], int]:
    """Newest first. `search` matches the file name or the reference number."""
    conditions = []
    if attention:
        conditions.append(attention_condition())
    if status is not None:
        conditions.append(File.status == status)
    if search:
        pattern = f"%{_escape_like(search)}%"
        conditions.append(
            or_(
                File.original_name.ilike(pattern, escape="\\"),
                File.ref_no.ilike(pattern, escape="\\"),
            )
        )

    total = await session.scalar(select(func.count()).select_from(File).where(*conditions))
    result = await session.execute(
        _files()
        .where(*conditions)
        .order_by(File.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(result.scalars()), total or 0


async def get_file_detail(session: AsyncSession, key: str | int) -> File | None:
    """A file with its receipts (vendor, line items), flags and runs loaded."""
    file = await get_file(session, key)
    if file is None:
        return None
    result = await session.execute(
        select(File)
        .where(File.id == file.id)
        .options(
            selectinload(File.duplicate_of),
            selectinload(File.receipts).selectinload(Receipt.vendor),
            selectinload(File.receipts).selectinload(Receipt.line_items),
            selectinload(File.flags),
            selectinload(File.runs),
        )
        .execution_options(populate_existing=True)
    )
    return result.scalar_one()


def attention_condition():
    """Files a person should look at: the Review queue (D-030 item 5)."""
    return or_(
        File.status.in_([FileStatus.NEEDS_REVIEW, FileStatus.FLAGGED]),
        File.open_flags > 0,
    )


async def file_counts(session: AsyncSession) -> dict[str, int | dict[FileStatus, int]]:
    rows = await session.execute(select(File.status, func.count()).group_by(File.status))
    by_status = {status: 0 for status in FileStatus}
    by_status.update({status: count for status, count in rows})
    with_warnings = await session.scalar(
        select(func.count())
        .select_from(File)
        .where(File.status == FileStatus.PARSED, File.open_flags > 0)
    )
    attention = await session.scalar(
        select(func.count()).select_from(File).where(attention_condition())
    )
    return {
        "total": sum(by_status.values()),
        "by_status": by_status,
        "with_warnings": with_warnings or 0,
        "needs_attention": attention or 0,
    }
