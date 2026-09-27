"""Phase 4 on a real database: warnings, the Review actions, summaries and reports.

The exit check: a broken sample lands in needs_review, is fixed by hand and becomes resolved.
"""

import io
import zipfile
from pathlib import Path

import pdfplumber
import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import Engine, text
from tests.fixtures.synthetic import Sample, all_samples
from tests.integration.test_pipeline import process, upload

pytestmark = pytest.mark.db

SAMPLES = {sample.name: sample for sample in all_samples()}


def xlsx(rows: list[list]) -> bytes:
    workbook = Workbook()
    for row in rows:
        workbook.active.append(row)
    out = io.BytesIO()
    workbook.save(out)
    return out.getvalue()


def bill(
    name: str,
    *,
    number: str,
    total: float,
    items: list[float],
    day: str = "14/08/2026",
    note: str | None = None,
) -> Sample:
    rows = [
        ["Vendor: Raju Hardware"],
        [f"Bill No: {number}"],
        [f"Date: {day}"],
        ["Description", "Amount"],
        *[[f"Item {i}", amount] for i, amount in enumerate(items, start=1)],
        [],
        ["Total", total],
    ]
    if note:
        rows.append([note])  # changes the bytes, not the receipt
    return Sample(name, xlsx(rows), "excel", "parsed")


def processed(api: TestClient, storage_dir: str, sample: Sample) -> dict:
    file = upload(api, sample)
    process(storage_dir, file["id"])
    return api.get(f"/files/{file['id']}").json()


def open_flag_types(detail: dict) -> list[str]:
    return sorted(flag["type"] for flag in detail["flags"] if not flag["resolved"])


EDIT = {
    "receipts": [
        {
            "vendor": "Raju Hardware",
            "receipt_number": "5512",
            "receipt_date": "2026-08-20",
            "total": "210.00",
            "line_items": [
                {"description": "Paint brush", "amount": "120.00"},
                {"description": "Nails (1 kg)", "quantity": "1", "amount": "90.00"},
            ],
        }
    ]
}


# --- warnings are stored with the receipts (D-029) -----------------------------------


def test_a_clean_file_is_parsed_without_flags(api: TestClient, storage_dir: str) -> None:
    detail = processed(api, storage_dir, SAMPLES["gst_tax_invoice.xlsx"])
    assert (detail["status"], detail["open_flags"], detail["flags"]) == ("parsed", 0, [])
    (receipt,) = detail["receipts"]
    assert (receipt["total"], len(receipt["line_items"])) == ("1888.00", 3)
    (run,) = detail["runs"]
    assert (run["parser"], run["accepted"], run["result"][0]["vendor"]) == (
        "excel",
        True,
        "Sharma Traders",
    )


def test_items_that_do_not_add_up_are_stored_with_a_warning(
    api: TestClient, storage_dir: str
) -> None:
    detail = processed(
        api, storage_dir, bill("off.xlsx", number="B-1", total=500, items=[100, 200])
    )

    assert detail["status"] == "parsed"
    assert len(detail["receipts"]) == 1  # stored and counted, despite the warning
    assert open_flag_types(detail) == ["arithmetic_mismatch"]
    assert detail["open_flags"] == 1
    assert "₹300.00" in detail["flags"][0]["detail"]
    assert detail["flags"][0]["receipt_id"] == detail["receipts"][0]["id"]


def test_a_date_before_last_financial_year_is_a_warning(api: TestClient, storage_dir: str) -> None:
    sample = bill("old.xlsx", number="B-2", total=100, items=[100], day="14/08/2023")
    detail = processed(api, storage_dir, sample)
    assert detail["status"] == "parsed"
    assert open_flag_types(detail) == ["validation_failed"]


def test_the_same_receipt_twice_is_flagged_as_a_duplicate(
    api: TestClient, storage_dir: str
) -> None:
    first = processed(api, storage_dir, bill("a.xlsx", number="B-3", total=100, items=[100]))
    second = processed(
        api,
        storage_dir,
        bill("b.xlsx", number="B-3", total=100, items=[100], note="Scanned again for records"),
    )

    assert first["flags"] == []
    assert open_flag_types(second) == ["duplicate_receipt"]
    assert first["receipts"][0]["ref_no"] in second["flags"][0]["detail"]


# --- the exit check: needs_review -> fixed by hand -> resolved (D-030) -----------------


def test_a_broken_file_is_fixed_by_hand_and_resolved(api: TestClient, storage_dir: str) -> None:
    broken = processed(api, storage_dir, SAMPLES["incomplete_bill.xlsx"])
    assert broken["status"] == "needs_review"
    assert broken["receipts"] == []
    assert broken["runs"][0]["result"][0]["vendor"] == "Raju Hardware"  # what the reader saw

    response = api.put(f"/files/{broken['ref_no']}/receipts", json=EDIT)

    assert response.status_code == 200, response.text
    fixed = response.json()
    assert (fixed["status"], fixed["error"], fixed["open_flags"]) == ("resolved", None, 0)
    (receipt,) = fixed["receipts"]
    assert (receipt["ref_no"], receipt["total"], receipt["receipt_date"]) == (
        f"{broken['ref_no']}-01",
        "210.00",
        "2026-08-20",
    )
    assert [i["description"] for i in receipt["line_items"]] == ["Paint brush", "Nails (1 kg)"]
    assert receipt["confidence"] is None  # entered by hand
    parsers = {run["parser"]: run["accepted"] for run in fixed["runs"]}
    assert parsers == {"manual": True, "excel": False}


def test_saving_resolves_the_warnings_the_person_has_seen(
    api: TestClient, storage_dir: str
) -> None:
    detail = processed(
        api, storage_dir, bill("off.xlsx", number="B-4", total=500, items=[100, 200])
    )
    edit = {
        "receipts": [
            {
                "vendor": "Raju Hardware",
                "receipt_number": "B-4",
                "receipt_date": "2026-08-14",
                "total": "500.00",
                "line_items": [{"description": "Item 1", "amount": "500.00"}],
            }
        ]
    }
    fixed = api.put(f"/files/{detail['id']}/receipts", json=edit).json()

    assert fixed["status"] == "resolved"
    assert fixed["open_flags"] == 0
    assert all(flag["resolved_by"] == "admin" for flag in fixed["flags"])


def test_editing_twice_replaces_the_receipts_and_keeps_the_history(
    api: TestClient, storage_dir: str
) -> None:
    detail = processed(api, storage_dir, SAMPLES["incomplete_bill.xlsx"])
    api.put(f"/files/{detail['id']}/receipts", json=EDIT)
    second = {"receipts": [EDIT["receipts"][0] | {"total": "215.00"}]}
    again = api.put(f"/files/{detail['id']}/receipts", json=second).json()

    assert [r["total"] for r in again["receipts"]] == ["215.00"]
    assert [run["accepted"] for run in again["runs"]] == [True, False, False]  # newest first


def test_a_category_can_be_chosen_when_saving(api: TestClient, storage_dir: str) -> None:
    detail = processed(api, storage_dir, SAMPLES["incomplete_bill.xlsx"])
    custom = api.post("/categories", json={"name": "Site repairs"}).json()

    edit = {"receipts": [EDIT["receipts"][0] | {"category_id": custom["id"]}]}
    fixed = api.put(f"/files/{detail['id']}/receipts", json=edit).json()
    assert fixed["receipts"][0]["category_id"] == custom["id"]

    unknown = {"receipts": [EDIT["receipts"][0] | {"category_id": 999_999}]}
    response = api.put(f"/files/{detail['id']}/receipts", json=unknown)
    assert (response.status_code, response.json()["code"]) == (422, "unknown_category")


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"vendor": "   "}, "vendor"),
        ({"total": "12.345"}, "total"),
        ({"receipt_date": "14/08/2026"}, "receipt_date"),
    ],
)
def test_bad_edits_are_refused(api: TestClient, storage_dir: str, change: dict, field: str) -> None:
    detail = processed(api, storage_dir, SAMPLES["incomplete_bill.xlsx"])
    response = api.put(
        f"/files/{detail['id']}/receipts", json={"receipts": [EDIT["receipts"][0] | change]}
    )
    assert response.status_code == 422
    assert field in response.json()["message"]
    assert api.get(f"/files/{detail['id']}").json()["status"] == "needs_review"


def test_a_file_being_processed_cannot_be_edited(
    api: TestClient, storage_dir: str, engine: Engine
) -> None:
    detail = processed(api, storage_dir, SAMPLES["incomplete_bill.xlsx"])
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE files SET status = 'processing' WHERE id = :id"), {"id": detail["id"]}
        )
    response = api.put(f"/files/{detail['id']}/receipts", json=EDIT)
    assert (response.status_code, response.json()["code"]) == (409, "file_busy")


# --- reject and mark as OK -------------------------------------------------------------


def test_rejecting_a_file(api: TestClient, storage_dir: str) -> None:
    detail = processed(api, storage_dir, SAMPLES["not_a_receipt.csv"])
    response = api.post(f"/files/{detail['id']}/reject", json={"reason": "Not a receipt"})

    assert response.status_code == 200
    assert (response.json()["status"], response.json()["error"]) == (
        "rejected",
        "Rejected: Not a receipt",
    )
    assert api.post(f"/files/{detail['id']}/reject", json={"reason": ""}).status_code == 422


def test_marking_a_warning_as_ok(api: TestClient, storage_dir: str) -> None:
    detail = processed(api, storage_dir, bill("off.xlsx", number="B-5", total=500, items=[100]))
    (flag,) = detail["flags"]

    response = api.post(f"/flags/{flag['id']}/resolve")
    assert response.status_code == 200
    assert (response.json()["resolved"], response.json()["resolved_by"]) == (True, "admin")

    after = api.get(f"/files/{detail['id']}").json()
    assert (after["status"], after["open_flags"]) == ("parsed", 0)
    assert api.post("/flags/999999/resolve").status_code == 404


# --- the Files page: counts, the review queue, previews, reports ---------------------


def test_summary_counts_and_the_review_queue(api: TestClient, storage_dir: str) -> None:
    processed(api, storage_dir, SAMPLES["gst_tax_invoice.xlsx"])  # parsed, clean
    warned = processed(api, storage_dir, bill("off.xlsx", number="B-6", total=9, items=[1]))
    broken = processed(api, storage_dir, SAMPLES["incomplete_bill.xlsx"])  # needs review
    unreadable = processed(api, storage_dir, SAMPLES["damaged.pdf"])  # flagged

    summary = api.get("/files/summary").json()
    assert summary["total"] == 4
    assert summary["by_status"]["parsed"] == 2
    assert summary["by_status"]["needs_review"] == 1
    assert summary["by_status"]["flagged"] == 1
    assert (summary["with_warnings"], summary["needs_attention"]) == (1, 3)

    queue = api.get("/files", params={"attention": "true"}).json()
    assert sorted(f["id"] for f in queue["items"]) == sorted(
        [warned["id"], broken["id"], unreadable["id"]]
    )


def test_pdfs_can_be_previewed_inline_but_spreadsheets_download(
    api: TestClient, storage_dir: str
) -> None:
    pdf = processed(api, storage_dir, SAMPLES["fuel_bill.pdf"])
    sheet = processed(api, storage_dir, SAMPLES["hotel_bill.xlsx"])

    shown = api.get(f"/files/{pdf['id']}/download", params={"inline": "true"})
    assert shown.headers["content-disposition"].startswith("inline")
    assert shown.headers["x-content-type-options"] == "nosniff"
    kept = api.get(f"/files/{sheet['id']}/download", params={"inline": "true"})
    assert kept.headers["content-disposition"].startswith("attachment")


def test_error_report_for_one_file(api: TestClient, storage_dir: str) -> None:
    detail = processed(api, storage_dir, bill("off.xlsx", number="B-7", total=500, items=[100]))

    response = api.get(f"/files/{detail['ref_no']}/error-report")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    with pdfplumber.open(io.BytesIO(response.content)) as document:
        text = document.pages[0].extract_text()
    assert detail["ref_no"] in text
    assert "Rs. 100.00" in text  # the mismatch, with the amount printed as Rs.


def test_all_error_reports_as_one_zip(api: TestClient, storage_dir: str) -> None:
    processed(api, storage_dir, SAMPLES["gst_tax_invoice.xlsx"])  # clean: not included
    broken = processed(api, storage_dir, SAMPLES["incomplete_bill.xlsx"])

    response = api.get("/files/error-reports.zip")

    assert response.status_code == 200
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    assert sorted(archive.namelist()) == [
        "error-report.pdf",
        f"originals/{broken['ref_no']} - incomplete_bill.xlsx",
    ]
    assert list((Path(storage_dir) / ".tmp").iterdir()) == []  # the zip is removed after sending
