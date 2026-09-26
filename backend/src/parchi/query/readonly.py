"""Read-only access for the Query page (D-038)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from parchi.db.session import get_sessionmaker

READER_ROLE = "parchi_reader"
STATEMENT_TIMEOUT = "5s"


@asynccontextmanager
async def reader_session() -> AsyncIterator[AsyncSession]:
    """A session that can only read `receipt_view`, and cannot write at all.

    The transaction is read-only and runs as `parchi_reader`; it is always rolled back.
    """
    async with get_sessionmaker()() as session:
        # SET TRANSACTION must be the first statement of the transaction.
        await session.execute(text("SET TRANSACTION READ ONLY"))
        await session.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'"))
        await session.execute(text(f"SET LOCAL ROLE {READER_ROLE}"))
        try:
            yield session
        finally:
            await session.rollback()
