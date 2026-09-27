"""The Query page: filtered receipts, their totals, and CSV export (D-038, D-039)."""

from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from parchi.api.deps import SessionDep
from parchi.api.errors import ErrorResponse
from parchi.db.enums import FileStatus
from parchi.db.models import File, Receipt, Vendor
from parchi.query import filters
from parchi.query.readonly import reader_session
from parchi.schemas.api import QUERY_PAGE_SIZE, ReceiptPage, ReceiptQuery
from parchi.validation import rules

router = APIRouter(tags=["query"])

# Files whose receipts are not counted until a person looks at them.
WAITING = (FileStatus.NEEDS_REVIEW, FileStatus.FLAGGED, FileStatus.AI_PROCESSING)


async def waiting_for_review(session: AsyncSession) -> int:
    count = await session.scalar(
        select(func.count()).select_from(File).where(File.status.in_(WAITING))
    )
    return count or 0


async def receipt_page(session: AsyncSession, query: ReceiptQuery) -> ReceiptPage:
    """Runs the filters on read-only access; `query` already has its dates."""
    async with reader_session() as reader:
        found = await filters.run(reader, query)
    return ReceiptPage(
        items=found.rows,
        count=found.count,
        sum_total=found.sum_total,
        average_total=found.average_total,
        page=query.page,
        page_size=QUERY_PAGE_SIZE,
        date_from=query.date_from,
        date_to=query.date_to,
        waiting_for_review=await waiting_for_review(session),
    )


@router.get("/receipts", responses={422: {"model": ErrorResponse}})
async def list_receipts(
    query: Annotated[ReceiptQuery, Query()], session: SessionDep
) -> ReceiptPage:
    """Receipts from parsed and resolved files. With no dates, the financial year to date."""
    return await receipt_page(session, filters.with_default_dates(query, rules.current_date()))


@router.get(
    "/receipts/export.csv",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/csv": {}}}, 422: {"model": ErrorResponse}},
)
async def export_receipts(query: Annotated[ReceiptQuery, Query()]) -> StreamingResponse:
    """Every matching receipt, one row each, whatever the page (D-039)."""
    query = filters.with_default_dates(query, rules.current_date())
    name = f"receipts_{query.date_from or 'start'}_to_{query.date_to or 'today'}.csv"
    return StreamingResponse(
        filters.csv_chunks(query),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/vendors")
async def list_vendors(session: SessionDep) -> list[str]:
    """Vendor names that have receipts, A to Z, for the Query page's vendor filter."""
    rows = await session.scalars(
        select(Vendor.normalized_name)
        .where(select(Receipt.id).where(Receipt.vendor_id == Vendor.id).exists())
        .distinct()
        .order_by(Vendor.normalized_name)
    )
    return list(rows)
