"""Phase 6 on a real database, with a fake provider: nothing is ever sent anywhere.

The exit check: a test proves no AI call happens without approval, and an approved run
records who approved it.
"""

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, text
from tests.fixtures.synthetic import all_samples
from tests.integration.test_pipeline import process, query, run, upload

from parchi.ai.base import AiCallError, AiInput, AiOutput, Approval, ApprovalMissingError
from parchi.config import get_settings
from parchi.db.enums import AiProvider
from parchi.db.session import get_engine, get_sessionmaker
from parchi.ingestion.storage import Storage
from parchi.pipeline import ai

pytestmark = pytest.mark.db

SAMPLES = {sample.name: sample for sample in all_samples()}


def answer(total: str = "210.00", day: str = "2026-08-20", vendor: str = "Raju Hardware") -> dict:
    return {
        "receipts": [
            {
                "vendor": vendor,
                "receipt_number": "5512",
                "receipt_date": day,
                "subtotal": None,
                "tax": None,
                "total": total,
                "line_items": [
                    {
                        "description": "Paint brush",
                        "quantity": "1",
                        "unit_price": None,
                        "amount": "120.00",
                    },
                    {
                        "description": "Nails",
                        "quantity": None,
                        "unit_price": None,
                        "amount": "90.00",
                    },
                ],
            }
        ]
    }


class FakeProvider:
    """Records every call; returns a scripted answer or raises a scripted error."""

    def __init__(self) -> None:
        self.calls: list[tuple[Approval, AiInput]] = []
        self.answer: dict = answer()
        self.error: str | None = None

    async def extract(self, approval: Approval, item: AiInput) -> AiOutput:
        self.calls.append((approval, item))
        if self.error:
            raise AiCallError(self.error)
        return AiOutput(self.answer, input_tokens=2000, output_tokens=300, request_id="req_x")


@pytest.fixture
def fake(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> FakeProvider:
    provider = FakeProvider()
    settings = get_settings()
    monkeypatch.setattr(settings, "ai_enabled", True)
    monkeypatch.setattr(settings, "anthropic_api_key", SecretStr("sk-test"))
    monkeypatch.setattr("parchi.ai.providers.get_provider", lambda _name: provider)
    queued: list[int] = []

    async def record(run_ids: list[int]) -> None:
        queued.extend(run_ids)

    monkeypatch.setattr("parchi.api.routes.ai.queue_ai_runs", record)
    provider.queued = queued  # type: ignore[attr-defined]
    return provider


def needs_review(api: TestClient, storage_dir: str, name: str = "incomplete_bill.xlsx") -> dict:
    file = upload(api, SAMPLES[name])
    process(storage_dir, file["id"])
    detail = api.get(f"/files/{file['id']}").json()
    assert detail["status"] == "needs_review"
    return detail


def approve(api: TestClient, ref: str, **body: Any) -> Any:
    return api.post(
        f"/files/{ref}/ai-extract", json={"provider": "anthropic", "approved": True} | body
    )


def run_ai(storage_dir: str, run_id: int) -> str:
    async def go() -> str:
        try:
            return await ai.run_ai(get_sessionmaker(), Storage(Path(storage_dir)), run_id)
        finally:
            await get_engine().dispose()

    return run(go())


# --- hard rule 1: no call without approval --------------------------------------------


def test_a_run_without_approval_can_never_reach_a_provider(
    api: TestClient, storage_dir: str, engine: Engine, fake: FakeProvider
) -> None:
    """The plan's approval test: the orchestrator raises and no adapter is called."""
    file = needs_review(api, storage_dir)
    (library_run,) = query(
        engine, "SELECT id FROM extraction_runs WHERE file_id = :f", f=file["id"]
    )

    with pytest.raises(ApprovalMissingError):
        run_ai(storage_dir, library_run.id)
    assert fake.calls == []

    # And the database itself refuses an AI run that carries no approval (D-012).
    with pytest.raises(Exception, match="ai_requires_approval"), engine.begin() as connection:
        connection.execute(
            text("INSERT INTO extraction_runs (file_id, parser) VALUES (:f, 'ai')"),
            {"f": file["id"]},
        )


@pytest.mark.parametrize("body", [{"approved": False}, {"approved": None}, {"approved": "yes"}])
def test_approval_must_be_explicit(
    api: TestClient, storage_dir: str, fake: FakeProvider, body
) -> None:
    file = needs_review(api, storage_dir)
    response = approve(api, file["ref_no"], **body)
    assert response.status_code == 422
    assert fake.queued == []  # type: ignore[attr-defined]
    missing = api.post(f"/files/{file['ref_no']}/ai-extract", json={"provider": "anthropic"})
    assert missing.status_code == 422


def test_ai_is_off_unless_switched_on(
    api: TestClient, storage_dir: str, engine: Engine, fake: FakeProvider, monkeypatch
) -> None:
    monkeypatch.setattr(get_settings(), "ai_enabled", False)
    file = needs_review(api, storage_dir)

    response = approve(api, file["ref_no"])

    assert (response.status_code, response.json()["code"]) == (403, "ai_disabled")
    assert query(engine, "SELECT id FROM extraction_runs WHERE parser = 'ai'") == []


def test_a_provider_without_a_key_cannot_be_used(
    api: TestClient, storage_dir: str, fake: FakeProvider
) -> None:
    file = needs_review(api, storage_dir)
    response = approve(api, file["ref_no"], provider="openai")  # only Claude has a key here
    assert (response.status_code, response.json()["code"]) == (409, "provider_not_configured")


def test_an_approved_run_records_who_approved_it_before_anything_is_sent(
    api: TestClient, storage_dir: str, engine: Engine, fake: FakeProvider
) -> None:
    file = needs_review(api, storage_dir)

    response = approve(api, file["ref_no"])

    assert response.status_code == 202
    (run_out,) = response.json()["runs"]
    (row,) = query(
        engine,
        "SELECT provider, model, ai_approved_by, ai_approved_at, finished_at FROM extraction_runs"
        " WHERE id = :r",
        r=run_out["run_id"],
    )
    assert (row.provider, row.model, row.ai_approved_by) == (
        "anthropic",
        "claude-sonnet-5",
        "local user",
    )
    assert row.ai_approved_at is not None and row.finished_at is None
    assert fake.calls == []  # approving sends nothing; the worker does, later
    assert fake.queued == [run_out["run_id"]]  # type: ignore[attr-defined]
    assert api.get(f"/files/{file['id']}").json()["status"] == "ai_processing"


# --- what happens to the result (D-036 item 4) ---------------------------------------------


def test_a_passing_result_is_stored_and_the_file_parsed(
    api: TestClient, storage_dir: str, engine: Engine, fake: FakeProvider
) -> None:
    file = needs_review(api, storage_dir)
    run_id = approve(api, file["ref_no"]).json()["runs"][0]["run_id"]

    assert run_ai(storage_dir, run_id) == "parsed"

    detail = api.get(f"/files/{file['id']}").json()
    assert detail["status"] == "parsed"
    (receipt,) = detail["receipts"]
    assert (receipt["total"], receipt["receipt_date"], len(receipt["line_items"])) == (
        "210.00",
        "2026-08-20",
        2,
    )
    ai_run = next(r for r in detail["runs"] if r["parser"] == "ai")
    assert (ai_run["accepted"], ai_run["input_tokens"], ai_run["output_tokens"]) == (
        True,
        2000,
        300,
    )
    (approval, item) = fake.calls[0]
    assert approval.run_id == run_id
    assert item.text is not None and "Raju Hardware" in item.text  # a spreadsheet goes as text
    assert run_ai(storage_dir, run_id) == "skipped"  # running it again does nothing
    assert len(fake.calls) == 1


def test_a_disagreement_with_the_library_is_flagged_for_a_person(
    api: TestClient, storage_dir: str, fake: FakeProvider
) -> None:
    file = needs_review(api, storage_dir)  # the library read the vendor as "Raju Hardware"
    fake.answer = answer(vendor="Raju Paints")
    run_id = approve(api, file["ref_no"]).json()["runs"][0]["run_id"]

    assert run_ai(storage_dir, run_id) == "conflict"

    detail = api.get(f"/files/{file['id']}").json()
    assert detail["status"] == "flagged"
    assert detail["receipts"] == []
    (flag,) = [f for f in detail["flags"] if not f["resolved"]]
    assert flag["type"] == "parser_conflict"
    assert "vendor (library Raju Hardware, AI Raju Paints)" in flag["detail"]


def test_a_failed_ai_call_flags_the_file(
    api: TestClient, storage_dir: str, fake: FakeProvider
) -> None:
    file = needs_review(api, storage_dir)
    fake.error = "Anthropic did not answer in time."
    run_id = approve(api, file["ref_no"]).json()["runs"][0]["run_id"]

    assert run_ai(storage_dir, run_id) == "failed"

    detail = api.get(f"/files/{file['id']}").json()
    assert detail["status"] == "flagged"
    assert "did not answer in time" in detail["error"]
    ai_run = next(r for r in detail["runs"] if r["parser"] == "ai")
    assert ai_run["error"] == "Anthropic did not answer in time."
    # A flagged file can be sent again, e.g. to the other provider.
    assert approve(api, file["ref_no"]).status_code == 202


def test_an_ai_result_that_fails_the_checks_is_not_stored(
    api: TestClient, storage_dir: str, fake: FakeProvider
) -> None:
    file = needs_review(api, storage_dir)
    fake.answer = answer(total="")  # no total
    run_id = approve(api, file["ref_no"]).json()["runs"][0]["run_id"]

    assert run_ai(storage_dir, run_id) == "failed"
    assert api.get(f"/files/{file['id']}").json()["receipts"] == []


def test_switching_ai_off_stops_approved_reads_that_have_not_run(
    api: TestClient, storage_dir: str, fake: FakeProvider, monkeypatch
) -> None:
    file = needs_review(api, storage_dir)
    run_id = approve(api, file["ref_no"]).json()["runs"][0]["run_id"]
    monkeypatch.setattr(get_settings(), "ai_enabled", False)

    assert run_ai(storage_dir, run_id) == "disabled"
    assert fake.calls == []
    assert api.get(f"/files/{file['id']}").json()["status"] == "needs_review"


# --- cache, cap, batches, eligibility ------------------------------------------------------


def test_identical_bytes_reuse_the_earlier_result_without_a_call(
    api: TestClient, storage_dir: str, engine: Engine, fake: FakeProvider
) -> None:
    first = needs_review(api, storage_dir)
    run_ai(storage_dir, approve(api, first["ref_no"]).json()["runs"][0]["run_id"])
    batch_id = api.post("/batches").json()["id"]
    copy = api.post(
        f"/batches/{batch_id}/files",
        files={
            "file": ("again.xlsx", SAMPLES["incomplete_bill.xlsx"].data, "application/octet-stream")
        },
        data={"confirm_duplicate": "true"},
    ).json()["file"]
    process(storage_dir, copy["id"])
    second_run = approve(api, copy["ref_no"]).json()["runs"][0]["run_id"]

    assert run_ai(storage_dir, second_run) == "parsed"

    assert len(fake.calls) == 1  # the second read cost nothing
    (row,) = query(engine, "SELECT cached_from_id FROM extraction_runs WHERE id = :r", r=second_run)
    assert row.cached_from_id is not None
    assert api.get("/ai/usage").json()["used_today"] == 1  # cached reads don't count


def test_the_daily_cap_is_enforced(
    api: TestClient, storage_dir: str, fake: FakeProvider, monkeypatch
) -> None:
    monkeypatch.setattr(get_settings(), "ai_daily_cap", 1)
    first = needs_review(api, storage_dir)
    second = needs_review(api, storage_dir, "expense_log.xlsx")

    assert approve(api, first["ref_no"]).status_code == 202
    response = approve(api, second["ref_no"])

    assert (response.status_code, response.json()["code"]) == (429, "daily_cap_reached")
    usage = api.get("/ai/usage").json()
    assert (usage["used_today"], usage["remaining"], usage["daily_cap"]) == (1, 0, 1)


def test_a_batch_is_approved_together(
    api: TestClient, storage_dir: str, fake: FakeProvider
) -> None:
    first = needs_review(api, storage_dir)
    second = needs_review(api, storage_dir, "expense_log.xlsx")

    response = api.post(
        "/files/ai-extract",
        json={
            "files": [first["ref_no"], str(second["id"])],
            "provider": "anthropic",
            "approved": True,
        },
    )

    assert response.status_code == 202
    assert sorted(r["ref_no"] for r in response.json()["runs"]) == sorted(
        [first["ref_no"], second["ref_no"]]
    )


def test_a_batch_with_an_ineligible_file_approves_none(
    api: TestClient, storage_dir: str, engine: Engine, fake: FakeProvider
) -> None:
    ok = needs_review(api, storage_dir)
    pending = upload(api, SAMPLES["fuel_bill.pdf"])  # not processed yet

    response = api.post(
        "/files/ai-extract",
        json={
            "files": [ok["ref_no"], pending["ref_no"]],
            "provider": "anthropic",
            "approved": True,
        },
    )

    assert (response.status_code, response.json()["code"]) == (409, "not_eligible")
    assert pending["ref_no"] in response.json()["message"]
    assert query(engine, "SELECT id FROM extraction_runs WHERE parser = 'ai'") == []


def test_usage_lists_the_providers(api: TestClient, fake: FakeProvider) -> None:
    usage = api.get("/ai/usage").json()
    providers = {p["provider"]: p for p in usage["providers"]}
    assert usage["enabled"] is True
    assert providers["anthropic"]["configured"] is True
    assert providers["openai"]["configured"] is False
    assert providers["openai"]["model"] == "gpt-6-sol"


def test_totals_parse_to_exact_decimals(fake: FakeProvider) -> None:
    from parchi.ai.prompt import to_receipts

    (receipt,) = to_receipts(answer(total="1,23,456.50"), "AI (Claude)")
    assert receipt.total == Decimal("123456.50")
    assert receipt.receipt_date == date(2026, 8, 20)
    assert AiProvider("anthropic") == AiProvider.ANTHROPIC
