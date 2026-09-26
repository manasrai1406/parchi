"""Phase 3 end to end on a real database: upload, process, and what gets stored.

The exit check: sample Excel and text-PDF receipts finish as parsed with the right totals.
"""

import asyncio
import sys
from collections.abc import Coroutine
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from tests.fixtures.synthetic import Sample, all_samples

from parchi.db.session import get_sessionmaker
from parchi.ingestion.storage import Storage
from parchi.pipeline.orchestrator import NO_OCR_YET, Outcome, process_file
from parchi.pipeline.recovery import files_to_queue

pytestmark = pytest.mark.db

SAMPLES = all_samples()


def run(coro: Coroutine[Any, Any, Any]) -> Any:
    # psycopg's async mode needs a selector loop on Windows.
    factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    return asyncio.run(coro, loop_factory=factory)


def upload(api: TestClient, sample: Sample) -> dict:
    batch_id = api.post("/batches").json()["id"]
    response = api.post(
        f"/batches/{batch_id}/files",
        files={"file": (sample.name, sample.data, "application/octet-stream")},
    )
    assert response.status_code == 201, response.text
    return response.json()["file"]


def process(storage_dir: str, file_id: int) -> Outcome:
    async def go() -> Outcome:
        try:
            return await process_file(get_sessionmaker(), Storage(Path(storage_dir)), file_id)
        finally:
            from parchi.db.session import get_engine

            await get_engine().dispose()

    return run(go())


def query(engine: Engine, sql: str, **params: Any) -> list[Any]:
    with engine.connect() as connection:
        return list(connection.execute(text(sql), params))


@pytest.mark.parametrize("sample", SAMPLES, ids=lambda s: s.name)
def test_every_sample_reaches_the_right_status_and_totals(
    api: TestClient, storage_dir: str, engine: Engine, sample: Sample
) -> None:
    file = upload(api, sample)
    assert api.queued == [file["id"]]  # type: ignore[attr-defined]

    process(storage_dir, file["id"])

    after = api.get(f"/files/{file['id']}").json()
    assert after["status"] == sample.status, after["error"]
    receipts = query(
        engine,
        "SELECT r.ref_no, r.total, r.receipt_date, v.raw_name, r.receipt_number"
        " FROM receipts r JOIN vendors v ON v.id = r.vendor_id"
        " WHERE r.file_id = :f ORDER BY r.seq",
        f=file["id"],
    )
    if sample.status == "parsed":
        assert after["error"] is None
        assert [(r.total, r.receipt_date, r.raw_name, r.receipt_number) for r in receipts] == [
            (e.total, e.receipt_date, e.vendor, e.receipt_number) for e in sample.receipts
        ]
        assert [r.ref_no for r in receipts] == [
            f"{file['ref_no']}-{seq:02d}" for seq in range(1, len(receipts) + 1)
        ]
    else:
        assert receipts == []  # nothing is stored until a person decides
        assert after["error"]


def test_a_parsed_file_has_one_accepted_run_with_items(
    api: TestClient, storage_dir: str, engine: Engine
) -> None:
    sample = next(s for s in SAMPLES if s.name == "gst_tax_invoice.xlsx")
    file = upload(api, sample)
    process(storage_dir, file["id"])

    (run_row,) = query(
        engine,
        "SELECT parser, accepted, provider, ai_approved_by, jsonb_array_length(result_json) AS n"
        " FROM extraction_runs WHERE file_id = :f",
        f=file["id"],
    )
    assert (run_row.parser, run_row.accepted, run_row.n) == ("excel", True, 1)
    assert run_row.provider is None and run_row.ai_approved_by is None  # library only
    items = query(
        engine,
        "SELECT li.description, li.amount FROM line_items li"
        " JOIN receipts r ON r.id = li.receipt_id WHERE r.file_id = :f ORDER BY li.position",
        f=file["id"],
    )
    assert [i.description for i in items] == ["A4 paper ream", "Stapler", "Box file"]
    kind = api.get(f"/files/{file['id']}").json()["kind"]
    assert kind == "excel"


def test_a_file_that_needs_review_keeps_its_result_on_the_run(
    api: TestClient, storage_dir: str, engine: Engine
) -> None:
    sample = next(s for s in SAMPLES if s.name == "incomplete_bill.xlsx")
    file = upload(api, sample)
    process(storage_dir, file["id"])

    (run_row,) = query(
        engine, "SELECT accepted, result_json FROM extraction_runs WHERE file_id = :f", f=file["id"]
    )
    assert run_row.accepted is False
    assert run_row.result_json[0]["vendor"] == "Raju Hardware"
    assert "date and total" in api.get(f"/files/{file['id']}").json()["error"]


def test_a_blank_scan_goes_to_review(api: TestClient, storage_dir: str, engine: Engine) -> None:
    """With OCR (Docker) the blank page is read and found empty; without it, the file
    waits with a note and no run is recorded, so it can be read later (D-032)."""
    from parchi.extraction import ocr

    sample = next(s for s in SAMPLES if s.name == "scanned_receipt.pdf")
    file = upload(api, sample)
    process(storage_dir, file["id"])

    after = api.get(f"/files/{file['id']}").json()
    runs = query(
        engine, "SELECT parser, accepted FROM extraction_runs WHERE file_id = :f", f=file["id"]
    )
    assert (after["status"], after["kind"]) == ("needs_review", "pdf_scan")
    if ocr.available():
        assert after["error"] == "No receipt could be found in this file."
        assert [tuple(r) for r in runs] == [("pdf_scan", False)]
    else:
        assert after["error"] == NO_OCR_YET
        assert runs == []


def test_unreadable_files_are_flagged(api: TestClient, storage_dir: str, engine: Engine) -> None:
    sample = next(s for s in SAMPLES if s.name == "damaged.pdf")
    file = upload(api, sample)
    process(storage_dir, file["id"])

    assert api.get(f"/files/{file['id']}").json()["status"] == "flagged"
    (flag,) = query(
        engine, "SELECT type, severity, resolved FROM flags WHERE file_id = :f", f=file["id"]
    )
    assert tuple(flag) == ("unreadable", "error", False)


def test_processing_twice_does_nothing_the_second_time(
    api: TestClient, storage_dir: str, engine: Engine
) -> None:
    sample = next(s for s in SAMPLES if s.name == "fuel_bill.pdf")
    file = upload(api, sample)

    assert process(storage_dir, file["id"]) == Outcome.PARSED
    assert process(storage_dir, file["id"]) == Outcome.SKIPPED
    assert len(query(engine, "SELECT id FROM receipts WHERE file_id = :f", f=file["id"])) == 1
    assert (
        len(query(engine, "SELECT id FROM extraction_runs WHERE file_id = :f", f=file["id"])) == 1
    )


def test_a_deleted_file_is_skipped(api: TestClient, storage_dir: str) -> None:
    sample = next(s for s in SAMPLES if s.name == "fuel_bill.pdf")
    file = upload(api, sample)
    api.delete(f"/files/{file['id']}")
    assert process(storage_dir, file["id"]) == Outcome.SKIPPED


def test_a_vendor_is_shared_between_receipts(
    api: TestClient, storage_dir: str, engine: Engine
) -> None:
    sample = next(s for s in SAMPLES if s.name == "three_bills.pdf")
    file = upload(api, sample)
    process(storage_dir, file["id"])

    vendors = query(engine, "SELECT raw_name FROM vendors")
    assert [v.raw_name for v in vendors] == ["Annapurna Tiffin Centre"]


def test_a_system_error_marks_the_file_failed_for_retry(
    api: TestClient, storage_dir: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample = next(s for s in SAMPLES if s.name == "fuel_bill.pdf")
    file = upload(api, sample)

    def broken(*args: object, **kwargs: object) -> None:
        raise OSError("disk went away")

    monkeypatch.setattr("parchi.pipeline.orchestrator.detect", broken)
    assert process(storage_dir, file["id"]) == Outcome.FAILED
    after = api.get(f"/files/{file['id']}").json()
    assert after["status"] == "failed"
    assert "retried" in after["error"]

    monkeypatch.undo()
    assert process(storage_dir, file["id"]) == Outcome.PARSED  # a failed file can be retried


# --- recovery (D-025) ------------------------------------------------------------------


def recoverable() -> list[int]:
    async def go() -> list[int]:
        try:
            async with get_sessionmaker()() as session:
                return await files_to_queue(session)
        finally:
            from parchi.db.session import get_engine

            await get_engine().dispose()

    return run(go())


def age(engine: Engine, file_id: int, status: str, seconds: int, attempts: int = 0) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE files SET status = :s, attempts = :a,"
                " status_changed_at = now() - make_interval(secs => :secs) WHERE id = :id"
            ),
            {"s": status, "a": attempts, "secs": seconds, "id": file_id},
        )


def test_recovery_queues_old_pending_files_only(api: TestClient, engine: Engine) -> None:
    fresh = upload(api, SAMPLES[0])["id"]
    old = upload(api, SAMPLES[1])["id"]
    age(engine, old, "pending", 120)

    assert recoverable() == [old]
    assert fresh not in recoverable()


def test_recovery_resets_files_stuck_in_processing(api: TestClient, engine: Engine) -> None:
    stuck = upload(api, SAMPLES[0])["id"]
    busy = upload(api, SAMPLES[1])["id"]
    age(engine, stuck, "processing", 11 * 60)
    age(engine, busy, "processing", 60)

    recoverable()

    status = dict(query(engine, "SELECT id, status FROM files"))
    assert status[stuck] == "pending"
    assert status[busy] == "processing"


def test_recovery_retries_failed_files_with_backoff_up_to_three_times(
    api: TestClient, engine: Engine
) -> None:
    due = upload(api, SAMPLES[0])["id"]
    waiting = upload(api, SAMPLES[1])["id"]
    exhausted = upload(api, SAMPLES[2])["id"]
    age(engine, due, "failed", 90, attempts=1)  # waits 1 minute after the 1st try
    age(engine, waiting, "failed", 90, attempts=2)  # waits 2 minutes after the 2nd
    age(engine, exhausted, "failed", 3600, attempts=3)

    assert recoverable() == [due]


def test_vendor_names_differing_only_in_case_share_one_normalized_name(
    api: TestClient, storage_dir: str, engine: Engine
) -> None:
    sample = next(s for s in SAMPLES if s.name == "marketplace_invoices.pdf")
    file = upload(api, sample)
    process(storage_dir, file["id"])

    vendors = query(engine, "SELECT raw_name, normalized_name FROM vendors ORDER BY id")
    assert [tuple(v) for v in vendors] == [
        ("Nova Retail Private Limited", "Nova Retail Private Limited"),
        ("NOVA RETAIL PRIVATE LIMITED", "Nova Retail Private Limited"),
    ]
