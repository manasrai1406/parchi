"""Run one file through the library pipeline: detect, extract, check, store (stages 3-7).

Library only. Nothing in this module calls an LLM (hard rules 1 and 2).
"""

import asyncio
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from parchi.db.enums import FileStatus, FlagSeverity, FlagType
from parchi.db.models import ExtractionRun, File, Flag, LineItem, Receipt, Vendor
from parchi.extraction.base import UnreadableFileError
from parchi.extraction.normalize import clean_vendor
from parchi.extraction.router import MIN_CONFIDENCE, extractor_for
from parchi.ingestion.detector import detect
from parchi.ingestion.storage import Storage
from parchi.logging import bind_context, get_logger
from parchi.schemas.receipt import ReceiptSchema
from parchi.validation.required import basic_problems, summarize

log = get_logger(__name__)

NO_OCR_YET = (
    "Scanned PDFs and photos are read with OCR, which is not available yet. "
    "Edit it by hand or wait for the OCR update."
)
SYSTEM_ERROR = "A system error stopped processing. It will be retried automatically."


class Outcome(StrEnum):
    SKIPPED = "skipped"
    PARSED = "parsed"
    NEEDS_REVIEW = "needs_review"
    UNREADABLE = "unreadable"
    FAILED = "failed"


@dataclass(frozen=True)
class Claimed:
    id: int
    ref_no: str
    storage_path: str


async def claim(session: AsyncSession, file_id: int) -> Claimed | None:
    """Move a file from pending (or failed) to processing in one statement, so two
    workers can never take the same file (D-025)."""
    async with session.begin():
        row = (
            await session.execute(
                update(File)
                .where(File.id == file_id, File.status.in_([FileStatus.PENDING, FileStatus.FAILED]))
                .values(
                    status=FileStatus.PROCESSING,
                    status_changed_at=text("now()"),
                    attempts=File.attempts + 1,
                    error=None,
                )
                .returning(File.id, File.ref_no, File.storage_path)
            )
        ).one_or_none()
    return Claimed(*row) if row else None


async def _finish(
    session: AsyncSession, file_id: int, status: FileStatus, error: str | None = None
) -> None:
    await session.execute(
        update(File)
        .where(File.id == file_id, File.status == FileStatus.PROCESSING)
        .values(status=status, status_changed_at=text("now()"), error=error)
    )


async def _vendor(session: AsyncSession, printed: str) -> Vendor:
    raw = clean_vendor(printed) or printed
    await session.execute(
        insert(Vendor)
        .values(raw_name=raw, normalized_name=raw)
        .on_conflict_do_nothing(index_elements=["raw_name"])
    )
    return (await session.execute(select(Vendor).where(Vendor.raw_name == raw))).scalar_one()


async def _store_receipts(
    session: AsyncSession, file: Claimed, run_id: int, receipts: list[ReceiptSchema]
) -> None:
    for seq, receipt in enumerate(receipts, start=1):
        if receipt.vendor is None or receipt.receipt_date is None or receipt.total is None:
            raise ValueError("An accepted receipt is missing a required field")
        vendor = await _vendor(session, receipt.vendor)
        row = Receipt(
            file_id=file.id,
            run_id=run_id,
            seq=seq,
            ref_no=f"{file.ref_no}-{seq:02d}",
            vendor_id=vendor.id,
            receipt_number=receipt.receipt_number,
            receipt_date=receipt.receipt_date,
            subtotal=receipt.subtotal,
            tax=receipt.tax,
            total=receipt.total,
            category_auto=vendor.default_category,
            confidence=receipt.confidence,
        )
        session.add(row)
        await session.flush()
        session.add_all(
            LineItem(
                receipt_id=row.id,
                position=position,
                description=item.description,
                quantity=item.quantity,
                unit_price=item.unit_price,
                amount=item.amount,
            )
            for position, item in enumerate(receipt.line_items, start=1)
        )


async def _mark_unreadable(session: AsyncSession, file: Claimed, reason: str) -> None:
    async with session.begin():
        await session.execute(
            insert(Flag)
            .values(
                file_id=file.id,
                type=FlagType.UNREADABLE,
                severity=FlagSeverity.ERROR,
                detail=reason,
                dedupe_key=f"unreadable:{file.id}",
            )
            .on_conflict_do_nothing()
        )
        await _finish(session, file.id, FileStatus.FLAGGED, reason)


async def process_file(
    sessions: async_sessionmaker[AsyncSession], storage: Storage, file_id: int
) -> Outcome:
    """Process one file. Safe to call twice: only a pending or failed file is taken."""
    async with sessions() as session:
        file = await claim(session, file_id)
    if file is None:
        log.info("pipeline.skipped", file_id=file_id)
        return Outcome.SKIPPED
    bind_context(file_id=file.id, ref_no=file.ref_no)
    log.info("pipeline.claimed")

    try:
        async with sessions() as session:
            return await _run(session, storage, file)
    except Exception:
        log.exception("pipeline.system_error")
        async with sessions() as session, session.begin():
            await _finish(session, file.id, FileStatus.FAILED, SYSTEM_ERROR)
        return Outcome.FAILED


async def _run(session: AsyncSession, storage: Storage, file: Claimed) -> Outcome:
    path = storage.absolute_path(file.storage_path)

    # Stage 3: detect.
    started = time.perf_counter()
    try:
        detection = await asyncio.to_thread(detect, path)
    except UnreadableFileError as exc:
        log.info("pipeline.detect.unreadable")
        await _mark_unreadable(session, file, str(exc))
        return Outcome.UNREADABLE
    async with session.begin():
        await session.execute(
            update(File)
            .where(File.id == file.id)
            .values(kind=detection.kind, mime_type=detection.mime_type)
        )
    log.info(
        "pipeline.detect.done",
        kind=detection.kind.value,
        duration_ms=round((time.perf_counter() - started) * 1000),
    )

    extractor = extractor_for(detection.kind)
    if extractor is None:
        # No run is recorded, so phase 5 can still record this file's one library run.
        async with session.begin():
            await _finish(session, file.id, FileStatus.NEEDS_REVIEW, NO_OCR_YET)
        log.info("pipeline.no_extractor", kind=detection.kind.value)
        return Outcome.NEEDS_REVIEW

    # Stages 4 and 5: extract and normalize (extractors return normalized receipts).
    started = time.perf_counter()
    receipts: list[ReceiptSchema] = []
    error: str | None = None
    unreadable = False
    try:
        receipts = await asyncio.to_thread(extractor.extract, path)
    except UnreadableFileError as exc:
        error, unreadable = str(exc), True
    except Exception as exc:  # a parser bug must not lose the file: a person reviews it
        log.exception("pipeline.extract.error", parser=extractor.parser.value)
        error = f"The {extractor.parser.value} reader failed ({type(exc).__name__})."
    duration_ms = round((time.perf_counter() - started) * 1000)
    log.info(
        "pipeline.extract.done",
        parser=extractor.parser.value,
        receipts=len(receipts),
        duration_ms=duration_ms,
        error=error is not None,
    )

    # Stage 6: check.
    problems = [] if error else basic_problems(receipts, MIN_CONFIDENCE[detection.kind])
    accepted = error is None and not problems

    # Stage 7: store, in one transaction.
    async with session.begin():
        run = ExtractionRun(
            file_id=file.id,
            parser=extractor.parser,
            result_json=None if error else [r.model_dump(mode="json") for r in receipts],
            confidence=min((r.confidence for r in receipts), default=None),
            duration_ms=duration_ms,
            accepted=accepted,
            error=error,
            finished_at=datetime.now(UTC),
        )
        session.add(run)
        await session.flush()
        bind_context(run_id=run.id)

        if unreadable:
            await session.execute(
                insert(Flag)
                .values(
                    file_id=file.id,
                    type=FlagType.UNREADABLE,
                    severity=FlagSeverity.ERROR,
                    detail=error,
                    dedupe_key=f"unreadable:{file.id}",
                )
                .on_conflict_do_nothing()
            )
            await _finish(session, file.id, FileStatus.FLAGGED, error)
            outcome = Outcome.UNREADABLE
        elif accepted:
            await _store_receipts(session, file, run.id, receipts)
            await _finish(session, file.id, FileStatus.PARSED)
            outcome = Outcome.PARSED
        else:
            await _finish(session, file.id, FileStatus.NEEDS_REVIEW, error or summarize(problems))
            outcome = Outcome.NEEDS_REVIEW

    log.info("pipeline.done", outcome=outcome.value, receipts=len(receipts))
    return outcome
