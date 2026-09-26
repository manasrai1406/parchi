"""Receipt filters as one SELECT on `receipt_view` (D-038, D-039)."""

import csv
import io
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from parchi.db.enums import FileStatus
from parchi.query.readonly import reader_session
from parchi.schemas.api import QUERY_PAGE_SIZE, ReceiptQuery, ReceiptRow
from parchi.validation.rules import financial_year_start

# Only receipts a person can rely on are counted; the rest wait for review.
COUNTED = (FileStatus.PARSED, FileStatus.RESOLVED)
CENT = Decimal("0.01")

receipt_view = sa.table(
    "receipt_view",
    sa.column("ref_no", sa.String),
    sa.column("file_ref_no", sa.String),
    sa.column("status", sa.String),
    sa.column("receipt_date", sa.Date),
    sa.column("vendor", sa.String),
    sa.column("receipt_number", sa.String),
    sa.column("category_id", sa.BigInteger),
    sa.column("category", sa.String),
    sa.column("subtotal", sa.Numeric(12, 2)),
    sa.column("tax", sa.Numeric(12, 2)),
    sa.column("total", sa.Numeric(12, 2)),
)
view = receipt_view.c
ROW_COLUMNS = (
    view.receipt_date,
    view.vendor,
    view.receipt_number,
    view.category,
    view.subtotal,
    view.tax,
    view.total,
    view.ref_no,
    view.file_ref_no,
)


def with_default_dates(query: ReceiptQuery, today: date) -> ReceiptQuery:
    """With neither date given, the financial year to date (D-028)."""
    if query.date_from is None and query.date_to is None:
        return query.model_copy(update={"date_from": financial_year_start(today), "date_to": today})
    return query


def statement(query: ReceiptQuery) -> sa.Select:
    """Every matching receipt, in order. Paging is added when it runs."""
    where = [view.status.in_([status.value for status in COUNTED])]
    if query.date_from and query.date_to:
        where.append(view.receipt_date.between(query.date_from, query.date_to))
    elif query.date_from:
        where.append(view.receipt_date >= query.date_from)
    elif query.date_to:
        where.append(view.receipt_date <= query.date_to)
    if query.vendor:
        where.append(view.vendor == query.vendor)
    if query.category_id is not None:
        where.append(view.category_id == query.category_id)
    if query.min_total is not None:
        where.append(view.total >= query.min_total)
    if query.max_total is not None:
        where.append(view.total <= query.max_total)

    order = (
        (view.total.desc(), view.receipt_date, view.ref_no)
        if query.sort == "amount"
        else (view.receipt_date, view.ref_no)
    )
    stmt = sa.select(*ROW_COLUMNS).where(*where).order_by(*order)
    return stmt.limit(query.limit) if query.limit else stmt


def to_sql(stmt: sa.Select) -> str:
    """The statement as it runs, values included, for showing to the person."""
    compiled = stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    return f"{compiled};"


@dataclass(frozen=True)
class Found:
    rows: list[ReceiptRow]
    count: int
    sum_total: Decimal
    average_total: Decimal | None


async def run(session: AsyncSession, query: ReceiptQuery) -> Found:
    """One page of rows, and totals over every match."""
    matching = statement(query)
    everything = matching.subquery()
    count, total, average = (
        await session.execute(
            sa.select(
                sa.func.count(),
                sa.func.coalesce(sa.func.sum(everything.c.total), 0),
                sa.func.avg(everything.c.total),
            ).select_from(everything)
        )
    ).one()

    offset = (query.page - 1) * QUERY_PAGE_SIZE
    size = QUERY_PAGE_SIZE if query.limit is None else min(QUERY_PAGE_SIZE, query.limit - offset)
    rows = []
    if size > 0:
        result = await session.execute(matching.limit(size).offset(offset))
        rows = [ReceiptRow.model_validate(row) for row in result.mappings()]
    return Found(
        rows=rows,
        count=count,
        sum_total=Decimal(total).quantize(CENT),
        average_total=None if average is None else Decimal(average).quantize(CENT),
    )


CSV_HEADER = (
    "Date",
    "Vendor",
    "Receipt no.",
    "Category",
    "Subtotal",
    "Tax",
    "Total",
    "Reference",
    "File",
)


def safe_cell(value: object) -> object:
    """Text a spreadsheet would run as a formula is prefixed with ' (D-039)."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return f"'{value}"
    return "" if value is None else value


async def csv_chunks(query: ReceiptQuery) -> AsyncIterator[str]:
    """Every matching receipt as CSV, one row per receipt, streamed."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)

    def take() -> str:
        text = buffer.getvalue()
        buffer.seek(0)
        buffer.truncate()
        return text

    # A byte-order mark so Excel reads the ₹ and other non-ASCII names correctly.
    writer.writerow(CSV_HEADER)
    yield "﻿" + take()
    async with reader_session() as session:
        result = await session.stream(statement(query))
        async for row in result:
            writer.writerow([safe_cell(value) for value in row])
            if buffer.tell() > 64_000:
                yield take()
    yield take()
