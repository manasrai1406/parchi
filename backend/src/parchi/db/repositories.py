"""Reusable queries."""

import re

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from parchi.db.enums import FileStatus
from parchi.db.models import File

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
    page: int,
    page_size: int,
) -> tuple[list[File], int]:
    """Newest first. `search` matches the file name or the reference number."""
    conditions = []
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
