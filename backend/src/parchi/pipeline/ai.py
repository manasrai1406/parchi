"""Opt-in AI extraction: approving files and running approved AI reads (D-036).

Hard rule 1: nothing here calls a provider unless the extraction run already records who
approved it, when, and for which provider. The API writes that approval first; the worker
turns it into an `Approval`, the only thing a provider accepts.
"""

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from datetime import time as day_time

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from parchi.ai import providers
from parchi.ai.base import AiCallError, Approval
from parchi.ai.inputs import build_input
from parchi.ai.prompt import to_receipts
from parchi.config import Settings, get_settings
from parchi.db.enums import AiProvider, FileStatus, FlagSeverity, FlagType, RunParser
from parchi.db.models import ExtractionRun, File, Flag, Receipt
from parchi.ingestion.storage import Storage
from parchi.logging import bind_context, get_logger
from parchi.pipeline.orchestrator import store_receipts
from parchi.schemas.receipt import ReceiptSchema
from parchi.validation import rules
from parchi.validation.required import basic_problems, summarize

log = get_logger(__name__)

# Files a person may send to AI: the reader failed, AI already failed, or warnings remain.
ELIGIBLE = (FileStatus.NEEDS_REVIEW, FileStatus.FLAGGED, FileStatus.PARSED)


class AiDisabledError(Exception):
    pass


class DailyCapReachedError(Exception):
    def __init__(self, remaining: int) -> None:
        super().__init__(remaining)
        self.remaining = remaining


class NotEligibleError(Exception):
    def __init__(self, ref_no: str, status: FileStatus) -> None:
        super().__init__(ref_no)
        self.ref_no = ref_no
        self.status = status


# --- approving (API side) ------------------------------------------------------------


def _start_of_today_utc(settings: Settings) -> datetime:
    today = rules.current_date()
    return datetime.combine(today, day_time.min, tzinfo=settings.tz).astimezone(UTC)


async def used_today(session: AsyncSession, settings: Settings) -> int:
    """Approved AI calls today (APP_TIMEZONE). Cached results cost nothing and don't count."""
    count = await session.scalar(
        select(func.count())
        .select_from(ExtractionRun)
        .where(
            ExtractionRun.parser == RunParser.AI,
            ExtractionRun.cached_from_id.is_(None),
            ExtractionRun.ai_approved_at >= _start_of_today_utc(settings),
        )
    )
    return count or 0


async def approve(
    session: AsyncSession,
    file_ids: list[int],
    provider: AiProvider,
    settings: Settings,
    approved_by: str,
) -> list[int]:
    """Record the approval on a new AI run per file, and mark the files ai_processing.
    Returns the run ids to queue. All or nothing: one ineligible file stops the batch."""
    if not settings.ai_enabled:
        raise AiDisabledError
    if not providers.is_configured(provider, settings):
        raise providers.ProviderNotConfiguredError(provider)
    async with session.begin():
        remaining = settings.ai_daily_cap - await used_today(session, settings)
        if len(file_ids) > remaining:
            raise DailyCapReachedError(max(remaining, 0))
        now = datetime.now(UTC)
        run_ids = []
        for file_id in file_ids:
            file = await session.get(File, file_id, with_for_update=True, populate_existing=True)
            if file is None:
                raise NotEligibleError(str(file_id), FileStatus.FAILED)
            if file.status not in ELIGIBLE:
                raise NotEligibleError(file.ref_no, file.status)
            run = ExtractionRun(
                file_id=file.id,
                parser=RunParser.AI,
                provider=provider,
                model=providers.model_for(provider, settings),
                ai_approved_by=approved_by,
                ai_approved_at=now,
            )
            session.add(run)
            await session.flush()
            file.status = FileStatus.AI_PROCESSING
            file.status_changed_at = now
            file.error = None
            run_ids.append(run.id)
    log.info("ai.approved", provider=provider.value, runs=len(run_ids))
    return run_ids


# --- running an approved read (worker side) -------------------------------------------


@dataclass(frozen=True)
class _Result:
    receipts: list[ReceiptSchema]
    input_tokens: int | None
    output_tokens: int | None
    cached_from_id: int | None


def _same(a: object, b: object) -> bool:
    if isinstance(a, str) and isinstance(b, str):
        return " ".join(a.split()).lower() == " ".join(b.split()).lower()
    return a == b


def conflicts(library: list[ReceiptSchema], ai: list[ReceiptSchema]) -> list[str]:
    """Where the library and the AI disagree on what matters: vendor, date, total."""
    found = [r for r in library if r.total is not None or r.receipt_date or r.vendor]
    if not found:
        return []
    if len(found) != len(ai):
        return [f"the number of receipts (library {len(found)}, AI {len(ai)})"]
    differences = []
    for index, (lib, got) in enumerate(zip(found, ai, strict=True), start=1):
        prefix = f"receipt {index}: " if len(ai) > 1 else ""
        for field, label in (("vendor", "vendor"), ("receipt_date", "date"), ("total", "total")):
            mine, theirs = getattr(lib, field), getattr(got, field)
            if mine is not None and theirs is not None and not _same(mine, theirs):
                differences.append(f"{prefix}{label} (library {mine}, AI {theirs})")
    return differences


def _library_result(run_rows: list[ExtractionRun]) -> list[ReceiptSchema]:
    for run in sorted(run_rows, key=lambda r: r.id, reverse=True):
        if run.parser not in (RunParser.AI, RunParser.MANUAL) and run.result_json:
            try:
                return [ReceiptSchema.model_validate(item) for item in run.result_json]
            except ValueError:
                return []
    return []


async def _cached(session: AsyncSession, run: ExtractionRun, sha256: str) -> ExtractionRun | None:
    """A successful AI read of identical bytes by the same provider and model (D-036)."""
    return await session.scalar(
        select(ExtractionRun)
        .join(File, File.id == ExtractionRun.file_id)
        .where(
            File.sha256 == sha256,
            ExtractionRun.parser == RunParser.AI,
            ExtractionRun.provider == run.provider,
            ExtractionRun.model == run.model,
            ExtractionRun.error.is_(None),
            ExtractionRun.result_json.is_not(None),
            ExtractionRun.finished_at.is_not(None),
            ExtractionRun.id != run.id,
        )
        .order_by(ExtractionRun.id.desc())
        .limit(1)
    )


async def _flag(session: AsyncSession, file_id: int, kind: FlagType, detail: str, key: str) -> None:
    await session.execute(
        insert(Flag)
        .values(
            file_id=file_id,
            type=kind,
            severity=FlagSeverity.WARNING,
            detail=detail,
            dedupe_key=key,
        )
        .on_conflict_do_nothing()
    )


@dataclass(frozen=True)
class _Job:
    """What the AI read needs, captured before any network call."""

    approval: Approval
    file_id: int
    path_in_storage: str
    kind: object
    name: str
    cached: _Result | None
    library: list[ReceiptSchema]


async def _load(session: AsyncSession, run_id: int) -> _Job | None:
    run = await session.get(ExtractionRun, run_id)
    if run is None:
        return None
    # First, before anything else: without a recorded approval, raise (hard rule 1).
    approval = Approval.from_run(run)
    if run.finished_at is not None:
        return None
    file = await session.get(File, run.file_id)
    if file is None:
        return None
    bind_context(file_id=file.id, ref_no=file.ref_no, run_id=run.id)
    cached_run = await _cached(session, run, file.sha256)
    cached = (
        _Result(
            [ReceiptSchema.model_validate(item) for item in cached_run.result_json],
            None,
            None,
            cached_run.id,
        )
        if cached_run is not None
        else None
    )
    runs = (
        await session.scalars(select(ExtractionRun).where(ExtractionRun.file_id == file.id))
    ).all()
    return _Job(
        approval=approval,
        file_id=file.id,
        path_in_storage=file.storage_path,
        kind=file.kind,
        name=file.original_name,
        cached=cached,
        library=_library_result(list(runs)),
    )


async def run_ai(sessions: async_sessionmaker[AsyncSession], storage: Storage, run_id: int) -> str:
    """Run one approved AI read. Safe to call twice: a finished run is skipped."""
    settings = get_settings()
    async with sessions() as session:
        # 1. Read what is needed, then end the transaction: the call below can take a while.
        async with session.begin():
            job = await _load(session, run_id)
        if job is None:
            log.info("ai.skipped", run_id=run_id)
            return "skipped"
        label = providers.LABELS[job.approval.provider]

        # 2. The call, with no transaction open. Only here is anything sent.
        started = time.perf_counter()
        error: str | None = None
        result = job.cached
        if not settings.ai_enabled:
            error, result = (
                "AI was switched off before this approved read ran. Nothing was sent.",
                None,
            )
        elif result is None:
            try:
                item = build_input(storage.absolute_path(job.path_in_storage), job.kind, job.name)
                provider = providers.get_provider(job.approval.provider)
                output = await provider.extract(job.approval, item)
                result = _Result(
                    to_receipts(output.data, source=f"AI ({label})"),
                    output.input_tokens,
                    output.output_tokens,
                    None,
                )
            except AiCallError as exc:
                error = str(exc)
        duration_ms = round((time.perf_counter() - started) * 1000)
        log.info(
            "ai.call.done",
            provider=job.approval.provider.value,
            model=job.approval.model,
            cached=bool(result and result.cached_from_id),
            input_tokens=result.input_tokens if result else None,
            output_tokens=result.output_tokens if result else None,
            duration_ms=duration_ms,
            error=error is not None,
        )

        # 3. Write the outcome in one transaction.
        async with session.begin():
            run = await session.get(
                ExtractionRun, run_id, with_for_update=True, populate_existing=True
            )
            file = await session.get(
                File, job.file_id, with_for_update=True, populate_existing=True
            )
            if run is None or file is None or run.finished_at is not None:
                return "skipped"
            run.finished_at = datetime.now(UTC)
            run.duration_ms = duration_ms
            if result is not None:
                run.result_json = [r.model_dump(mode="json") for r in result.receipts]
                run.input_tokens = result.input_tokens
                run.output_tokens = result.output_tokens
                run.cached_from_id = result.cached_from_id
                run.confidence = min((r.confidence for r in result.receipts), default=None)
            outcome = await _decide(session, file, run, result, error, job.library, label, settings)
            file.status_changed_at = datetime.now(UTC)
    log.info("ai.done", outcome=outcome)
    return outcome


async def _decide(
    session: AsyncSession,
    file: File,
    run: ExtractionRun,
    result: _Result | None,
    error: str | None,
    library: list[ReceiptSchema],
    label: str,
    settings: Settings,
) -> str:
    """Store, flag, or send back, as D-036 item 4 says."""
    if error is not None or result is None:
        run.error = error or "The AI read failed."
        if not settings.ai_enabled:
            file.status, file.error = FileStatus.NEEDS_REVIEW, run.error
            return "disabled"
        detail = f"{label} could not read this file: {run.error}"
        await _flag(session, file.id, FlagType.VALIDATION_FAILED, detail, f"ai-failed:{run.id}")
        file.status, file.error = FileStatus.FLAGGED, detail
        return "failed"

    problems = basic_problems(result.receipts, 0.0)
    if problems:
        detail = f"{label}'s result also failed the checks: {summarize(problems)}"
        await _flag(session, file.id, FlagType.VALIDATION_FAILED, detail, f"ai-failed:{run.id}")
        file.status, file.error = FileStatus.FLAGGED, detail
        return "failed"

    differences = conflicts(library, result.receipts)
    if differences:
        detail = f"The library and {label} disagree on " + "; ".join(differences) + "."
        await _flag(session, file.id, FlagType.PARSER_CONFLICT, detail, f"conflict:{run.id}")
        file.status, file.error = (
            FileStatus.FLAGGED,
            "The readers disagree. Choose on the Review page.",
        )
        return "conflict"

    # Accepted: this run's receipts replace whatever was stored (D-013 item 5).
    await session.execute(
        update(ExtractionRun)
        .where(ExtractionRun.file_id == file.id, ExtractionRun.accepted.is_(True))
        .values(accepted=False)
    )
    await session.execute(delete(Receipt).where(Receipt.file_id == file.id))
    run.accepted = True
    await session.flush()
    receipt_ids = await store_receipts(session, file.id, file.ref_no, run.id, result.receipts)
    # Earlier problems belonged to the earlier result; the person approved this read.
    await session.execute(
        update(Flag)
        .where(Flag.file_id == file.id, Flag.resolved.is_(False))
        .values(resolved=True, resolved_by=run.ai_approved_by, resolved_at=text("now()"))
    )
    problems_now = await rules.check_receipts(
        session, result.receipts, file.id, rules.current_date()
    )
    await rules.record_problems(session, file.id, receipt_ids, problems_now)
    file.status, file.error = FileStatus.PARSED, None
    return "parsed"
