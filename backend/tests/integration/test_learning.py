"""Learning a vendor's labels from corrections, and keeping receipts as tests (D-048)."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from tests.fixtures.synthetic import Sample
from tests.integration.test_pipeline import process, upload
from tests.integration.test_review import xlsx

pytestmark = pytest.mark.db


def bill(vendor: str, number: str, items: list[int], label: str = "Kul Rashi", extra=()) -> Sample:
    """A spreadsheet bill whose total carries a label the reader does not know."""
    rows = [
        [f"Vendor: {vendor}"],
        [f"Bill No: {number}"],
        ["Date: 14/08/2026"],
        ["Description", "Amount"],
        *[[f"Item {i}", amount] for i, amount in enumerate(items, start=1)],
        [],
        [label, sum(items)],
        *extra,
    ]
    return Sample(f"{vendor}_{number}.xlsx", xlsx(rows), "excel", "parsed")


def read(api: TestClient, storage_dir: str, sample: Sample) -> dict:
    file = upload(api, sample)
    process(storage_dir, file["id"])
    return api.get(f"/files/{file['id']}").json()


def correct(api: TestClient, detail: dict, vendor: str, total: str, **extra) -> dict:
    receipt = {
        "vendor": vendor,
        "receipt_number": detail["runs"][-1]["result"][0]["receipt_number"],
        "receipt_date": "2026-08-14",
        "total": total,
    }
    response = api.put(f"/files/{detail['id']}/receipts", json={"receipts": [receipt], **extra})
    assert response.status_code == 200, response.text
    return response.json()


def labels(engine: Engine) -> list[tuple]:
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT vendor_key, field, label, taught_by FROM vendor_labels ORDER BY id")
        ).all()


def test_a_correction_teaches_the_vendors_total_label(
    api: TestClient, storage_dir: str, engine: Engine
) -> None:
    first = read(api, storage_dir, bill("Sharma Stores", "A1", [500, 90]))
    assert first["status"] == "needs_review"  # "Kul Rashi" is not a known label

    saved = correct(api, first, "Sharma Stores", "590")

    assert saved["learned"] == [{"vendor": "Sharma Stores", "field": "total", "label": "kul rashi"}]
    assert labels(engine) == [("sharma stores", "total", "kul rashi", "admin")]

    # The next bill from the same vendor is read without help.
    second = read(api, storage_dir, bill("Sharma Stores", "A2", [600, 100]))
    assert second["status"] == "parsed", second["error"]
    assert second["receipts"][0]["total"] == "700.00"
    with engine.connect() as connection:
        used = connection.execute(text("SELECT times_used FROM vendor_labels")).scalar_one()
    assert used == 1


def test_a_label_is_shared_once_three_vendors_taught_it(api: TestClient, storage_dir: str) -> None:
    other = read(api, storage_dir, bill("Fourth Vendor", "D0", [50, 50]))
    assert other["status"] == "needs_review"  # one vendor's lesson is not shared yet

    for vendor in ("First Vendor", "Second Vendor", "Third Vendor"):
        detail = read(api, storage_dir, bill(vendor, "X1", [100, 20]))
        correct(api, detail, vendor, "120")

    fourth = read(api, storage_dir, bill("Fourth Vendor", "D1", [300, 30]))
    assert fourth["status"] == "parsed", fourth["error"]
    assert fourth["receipts"][0]["total"] == "330.00"


def test_nothing_is_learned_when_the_amount_is_ambiguous(
    api: TestClient, storage_dir: str, engine: Engine
) -> None:
    detail = read(
        api, storage_dir, bill("Guess Mart", "G1", [500, 90], extra=[["Paid by card", 590]])
    )
    saved = correct(api, detail, "Guess Mart", "590")
    assert saved["learned"] == []
    assert labels(engine) == []


def test_nothing_is_learned_when_the_reader_was_right(
    api: TestClient, storage_dir: str, engine: Engine
) -> None:
    detail = read(api, storage_dir, bill("Right Store", "R1", [500, 90], label="Grand Total"))
    assert detail["status"] == "parsed"
    saved = correct(api, detail, "Right Store", "590")
    assert saved["learned"] == []
    assert labels(engine) == []


def test_a_corrected_receipt_can_be_kept_as_a_test(
    api: TestClient, storage_dir: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from parchi.config import get_settings

    kept_dir = tmp_path / "real"
    monkeypatch.setattr(get_settings(), "real_samples_dir", kept_dir)
    sample = bill("Keep Store", "K1", [500, 90])
    detail = read(api, storage_dir, sample)

    saved = correct(api, detail, "Keep Store", "590", keep_as_test=True)

    assert saved["kept_as_test"] is True
    name = f"{detail['ref_no']}__{sample.name}"
    assert (kept_dir / name).read_bytes() == sample.data
    answers = json.loads((kept_dir / "answers.json").read_text(encoding="utf-8"))
    assert answers[name] == [
        {
            "vendor": "Keep Store",
            "receipt_number": "K1",
            "receipt_date": "2026-08-14",
            "subtotal": None,
            "tax": None,
            "total": "590.00",
        }
    ]


def test_nothing_is_kept_unless_asked(
    api: TestClient, storage_dir: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from parchi.config import get_settings

    monkeypatch.setattr(get_settings(), "real_samples_dir", tmp_path / "real")
    detail = read(api, storage_dir, bill("Skip Store", "S1", [500, 90]))
    assert correct(api, detail, "Skip Store", "590")["kept_as_test"] is False
    assert not (tmp_path / "real").exists()


def test_the_check_script_reads_kept_receipts_back(
    api: TestClient, storage_dir: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    import asyncio
    import importlib.util
    import sys

    from parchi.config import get_settings

    kept_dir = tmp_path / "real"
    monkeypatch.setattr(get_settings(), "real_samples_dir", kept_dir)
    detail = read(api, storage_dir, bill("Check Store", "C1", [500, 90]))
    correct(api, detail, "Check Store", "590", keep_as_test=True)

    spec = importlib.util.spec_from_file_location(
        "check_real_samples", Path(__file__).parents[2] / "scripts" / "check_real_samples.py"
    )
    assert spec and spec.loader
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    loop = asyncio.SelectorEventLoop if sys.platform == "win32" else None

    # The library alone misses the unknown label; with what it learned, it reads it.
    assert asyncio.run(script.check(kept_dir, learned=False), loop_factory=loop) == 1
    assert "expected 590.00, read None" in capsys.readouterr().out
    assert asyncio.run(script.check(kept_dir, learned=True), loop_factory=loop) == 0
    assert "1 of 1 kept receipts read correctly" in capsys.readouterr().out
