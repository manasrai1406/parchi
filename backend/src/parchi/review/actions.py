"""What a person does on the Review page: save edits, reject a file, mark a flag OK (D-030)."""

from datetime import UTC, date, datetime

from sqlalchemy import delete, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from parchi.db.enums import FileStatus, RunParser
from parchi.db.models import Category, ExtractionRun, File, Flag, Receipt
from parchi.ingestion.deletion import BUSY_STATUSES, FileBusyError, FileNotFoundInDbError
from parchi.logging import bind_context, get_logger
from parchi.pipeline.orchestrator import store_receipts
from parchi.schemas.api import ReceiptIn
from parchi.schemas.receipt import LineItemSchema, ReceiptSchema
from parchi.validation.rules import check_receipts, record_problems

log = get_logger(__name__)


class UnknownCategoryError(ValueError):
    pass


class FlagNotFoundError(LookupError):
    pass


async def _lock_file(session: AsyncSession, file_id: int) -> File:
    file = await session.get(File, file_id, with_for_update=True, populate_existing=True)
    if file is None:
        raise FileNotFoundInDbError(file_id)
    if file.status in BUSY_STATUSES:
        raise FileBusyError("This file is being processed. Try again when it finishes.")
    bind_context(file_id=file.id, ref_no=file.ref_no)
    return file


async def _resolve_open_flags(session: AsyncSession, file_id: int, user: str) -> None:
    await session.execute(
        update(Flag)
        .where(Flag.file_id == file_id, Flag.resolved.is_(False))
        .values(resolved=True, resolved_by=user, resolved_at=text("now()"))
    )


def _as_schema(receipt: ReceiptIn) -> ReceiptSchema:
    return ReceiptSchema(
        vendor=receipt.vendor,
        receipt_number=receipt.receipt_number,
        receipt_date=receipt.receipt_date,
        subtotal=receipt.subtotal,
        tax=receipt.tax,
        total=receipt.total,
        line_items=[
            LineItemSchema(
                description=item.description,
                quantity=item.quantity,
                unit_price=item.unit_price,
                amount=item.amount,
            )
            for item in receipt.line_items
        ],
        confidence=1.0,
        source="entered by hand",
    )


async def save_manual(
    session: AsyncSession, file_id: int, receipts: list[ReceiptIn], user: str, today: date
) -> None:
    """Record a person's edits as the accepted `manual` run and resolve the file."""
    async with session.begin():
        file = await _lock_file(session, file_id)

        category_ids = {r.category_id for r in receipts if r.category_id is not None}
        if category_ids:
            found = set(
                await session.scalars(select(Category.id).where(Category.id.in_(category_ids)))
            )
            if missing := category_ids - found:
                raise UnknownCategoryError(f"Unknown category: {sorted(missing)[0]}")

        schemas = [_as_schema(receipt) for receipt in receipts]
        # The new run replaces the accepted one; earlier runs stay as history.
        await session.execute(
            update(ExtractionRun)
            .where(ExtractionRun.file_id == file.id, ExtractionRun.accepted.is_(True))
            .values(accepted=False)
        )
        await session.execute(delete(Receipt).where(Receipt.file_id == file.id))
        run = ExtractionRun(
            file_id=file.id,
            parser=RunParser.MANUAL,
            result_json=[schema.model_dump(mode="json") for schema in schemas],
            accepted=True,
            finished_at=datetime.now(UTC),
        )
        session.add(run)
        await session.flush()
        bind_context(run_id=run.id)

        receipt_ids = await store_receipts(
            session, file.id, file.ref_no, run.id, schemas, manual=True
        )
        for receipt_id, receipt in zip(receipt_ids, receipts, strict=True):
            if receipt.category_id is not None:
                await session.execute(
                    update(Receipt)
                    .where(Receipt.id == receipt_id)
                    .values(category_override_id=receipt.category_id)
                )

        # The person has seen the problems and decided: remaining ones are resolved (D-030).
        await _resolve_open_flags(session, file.id, user)
        problems = await check_receipts(session, schemas, file.id, today)
        await record_problems(session, file.id, receipt_ids, problems, resolved_by=user)

        file.status = FileStatus.RESOLVED
        file.error = None
        file.status_changed_at = datetime.now(UTC)
    log.info("review.saved", receipts=len(receipts), warnings=len(problems))


async def reject_file(session: AsyncSession, file_id: int, reason: str, user: str) -> None:
    """Not a receipt, or a bad scan. Its receipts drop out of queries (D-030 item 4)."""
    async with session.begin():
        file = await _lock_file(session, file_id)
        await _resolve_open_flags(session, file.id, user)
        file.status = FileStatus.REJECTED
        file.error = f"Rejected: {' '.join(reason.split())}"
        file.status_changed_at = datetime.now(UTC)
    log.info("review.rejected")


async def resolve_flag(session: AsyncSession, flag_id: int, user: str) -> Flag:
    """Mark one warning as looked at and OK (D-030 item 3)."""
    async with session.begin():
        flag = await session.get(Flag, flag_id, with_for_update=True)
        if flag is None:
            raise FlagNotFoundError(flag_id)
        bind_context(file_id=flag.file_id)
        if not flag.resolved:
            flag.resolved = True
            flag.resolved_by = user
            flag.resolved_at = datetime.now(UTC)
    log.info("review.flag_resolved", flag_id=flag_id, flag_type=flag.type.value)
    return flag
