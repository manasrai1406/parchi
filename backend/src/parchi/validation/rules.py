"""Checks on receipts that are complete enough to store (D-029).

A failed check does not stop a file: the receipts are stored and each problem becomes
an open warning flag. Messages name fields and amounts the person needs to see, and are
stored in the flags table; they are never logged.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from parchi.config import get_settings
from parchi.db.enums import FileStatus, FlagSeverity, FlagType
from parchi.db.models import File, Flag, Receipt, Vendor
from parchi.schemas.receipt import ReceiptSchema

TOLERANCE = Decimal("1.00")  # rupees; also absorbs a printed "Round Off" (D-029 item 1)


@dataclass(frozen=True)
class Problem:
    type: FlagType
    detail: str
    receipt_seq: int  # 1-based position of the receipt in its file
    key: str  # what makes this problem the same problem next time (dedupe)
    severity: FlagSeverity = FlagSeverity.WARNING


def _close(a: Decimal, b: Decimal) -> bool:
    return abs(a - b) <= TOLERANCE


def _rupees(amount: Decimal) -> str:
    return f"₹{amount:,.2f}"


def arithmetic_problems(receipt: ReceiptSchema, seq: int) -> list[Problem]:
    problems = []
    total = receipt.total
    if receipt.subtotal is not None and receipt.tax is not None and total is not None:
        expected = receipt.subtotal + receipt.tax
        if not _close(expected, total):
            problems.append(
                Problem(
                    FlagType.ARITHMETIC_MISMATCH,
                    f"Subtotal {_rupees(receipt.subtotal)} + tax {_rupees(receipt.tax)} = "
                    f"{_rupees(expected)}, but the total is {_rupees(total)}.",
                    seq,
                    "subtotal+tax",
                )
            )
    if receipt.line_items:
        items = sum((item.amount for item in receipt.line_items), Decimal("0"))
        targets = [value for value in (receipt.subtotal, total) if value is not None]
        if targets and not any(_close(items, target) for target in targets):
            against = " or ".join(
                f"the {name} {_rupees(value)}"
                for name, value in (("subtotal", receipt.subtotal), ("total", total))
                if value is not None
            )
            problems.append(
                Problem(
                    FlagType.ARITHMETIC_MISMATCH,
                    f"Line items add up to {_rupees(items)}, which does not match {against}.",
                    seq,
                    "items",
                )
            )
    return problems


def current_date() -> date:
    """Today in APP_TIMEZONE. The one place checks get today from, so tests can pin it."""
    return datetime.now(get_settings().tz).date()


def financial_year_start(today: date) -> date:
    """1 April of the Indian financial year that contains `today`."""
    year = today.year if today.month >= 4 else today.year - 1
    return date(year, 4, 1)


def date_problems(receipt: ReceiptSchema, seq: int, today: date) -> list[Problem]:
    """Plausible: from 1 April of the previous financial year up to today (D-029 item 2)."""
    when = receipt.receipt_date
    if when is None:
        return []
    this_year = financial_year_start(today)
    earliest = this_year.replace(year=this_year.year - 1)
    if when > today:
        detail = f"The date {when:%d %b %Y} is in the future."
    elif when < earliest:
        detail = (
            f"The date {when:%d %b %Y} is before {earliest:%d %b %Y}, "
            "the start of last financial year."
        )
    else:
        return []
    return [Problem(FlagType.VALIDATION_FAILED, detail, seq, "date")]


async def duplicate_problems(
    session: AsyncSession, receipt: ReceiptSchema, seq: int, file_id: int
) -> list[Problem]:
    """Another stored receipt with the same vendor, number and total (D-029 item 3)."""
    if receipt.vendor is None or receipt.total is None:
        return []
    query = (
        select(Receipt.ref_no)
        .join(Vendor, Vendor.id == Receipt.vendor_id)
        .join(File, File.id == Receipt.file_id)
        .where(
            func.lower(Vendor.normalized_name) == receipt.vendor.lower(),
            Receipt.total == receipt.total,
            Receipt.file_id != file_id,
            File.status.in_([FileStatus.PARSED, FileStatus.RESOLVED]),
        )
        .order_by(Receipt.id)
        .limit(1)
    )
    if receipt.receipt_number:
        query = query.where(Receipt.receipt_number == receipt.receipt_number)
    elif receipt.receipt_date is not None:
        query = query.where(Receipt.receipt_date == receipt.receipt_date)
    else:
        return []
    other = await session.scalar(query)
    if other is None:
        return []
    return [
        Problem(
            FlagType.DUPLICATE_RECEIPT,
            f"The same receipt (vendor, number and total) is already stored as {other}.",
            seq,
            f"duplicate-of:{other}",
        )
    ]


async def check_receipts(
    session: AsyncSession, receipts: list[ReceiptSchema], file_id: int, today: date
) -> list[Problem]:
    problems: list[Problem] = []
    for seq, receipt in enumerate(receipts, start=1):
        problems += arithmetic_problems(receipt, seq)
        problems += date_problems(receipt, seq, today)
        problems += await duplicate_problems(session, receipt, seq, file_id)
    return problems


async def record_problems(
    session: AsyncSession,
    file_id: int,
    receipt_ids: list[int],
    problems: list[Problem],
    resolved_by: str | None = None,
) -> None:
    """Write problems as flags on their receipts. Open flags are not duplicated
    (dedupe key); passing resolved_by records them as already resolved (D-030)."""
    for problem in problems:
        values = {
            "file_id": file_id,
            "receipt_id": receipt_ids[problem.receipt_seq - 1],
            "type": problem.type,
            "severity": problem.severity,
            "detail": problem.detail,
            "dedupe_key": f"{file_id}:{problem.receipt_seq}:{problem.key}",
        }
        if resolved_by is not None:
            values |= {"resolved": True, "resolved_by": resolved_by, "resolved_at": func.now()}
        await session.execute(insert(Flag).values(**values).on_conflict_do_nothing())
