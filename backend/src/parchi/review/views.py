"""Shape a loaded file (get_file_detail) into what the Review page and the report show."""

from pydantic import ValidationError

from parchi.db.models import File
from parchi.schemas.api import FileDetail, FileSummary, FlagOut, LineItemOut, ReceiptOut, RunOut
from parchi.schemas.receipt import ReceiptSchema


def _result(result_json: object) -> list[ReceiptSchema] | None:
    if not isinstance(result_json, list):
        return None
    try:
        return [ReceiptSchema.model_validate(item) for item in result_json]
    except ValidationError:
        return None  # a result from an older shape; the run itself is still listed


def file_detail(file: File) -> FileDetail:
    summary = FileSummary.model_validate(file)
    return FileDetail(
        **summary.model_dump(),
        receipts=[
            ReceiptOut(
                id=r.id,
                ref_no=r.ref_no,
                seq=r.seq,
                vendor=r.vendor.raw_name,
                receipt_number=r.receipt_number,
                receipt_date=r.receipt_date,
                subtotal=r.subtotal,
                tax=r.tax,
                total=r.total,
                category_id=r.category_id,
                category_auto_id=r.category_auto_id,
                category_override_id=r.category_override_id,
                confidence=r.confidence,
                line_items=[LineItemOut.model_validate(item) for item in r.line_items],
            )
            for r in sorted(file.receipts, key=lambda r: r.seq)
        ],
        flags=[
            FlagOut.model_validate(flag)
            for flag in sorted(file.flags, key=lambda f: (f.resolved, f.id))
        ],
        runs=[
            RunOut(
                id=run.id,
                parser=run.parser,
                provider=run.provider,
                model=run.model,
                confidence=run.confidence,
                duration_ms=run.duration_ms,
                accepted=run.accepted,
                error=run.error,
                ai_approved_by=run.ai_approved_by,
                ai_approved_at=run.ai_approved_at,
                finished_at=run.finished_at,
                created_at=run.created_at,
                input_tokens=run.input_tokens,
                output_tokens=run.output_tokens,
                cached_from_id=run.cached_from_id,
                result=_result(run.result_json),
            )
            for run in sorted(file.runs, key=lambda r: r.id, reverse=True)
        ],
    )
