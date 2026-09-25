"""D-019: deleting files, their history, copies and stored bytes."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

pytestmark = pytest.mark.db

PDF = b"%PDF-1.4 hotel bill" * 50


def upload(api: TestClient, batch_id: int, data: bytes = PDF, confirm: bool = False) -> dict:
    response = api.post(
        f"/batches/{batch_id}/files",
        files={"file": ("bill.pdf", data, "application/pdf")},
        data={"confirm_duplicate": "true" if confirm else "false"},
    )
    return response.json()["file"]


@pytest.fixture
def batch_id(api: TestClient) -> int:
    return api.post("/batches").json()["id"]


def stored(storage_dir: str) -> list[Path]:
    return [p for p in Path(storage_dir).rglob("*") if p.is_file()]


def count(engine: Engine, sql: str) -> int:
    with engine.connect() as connection:
        return connection.execute(text(sql)).scalar_one()


def test_delete_removes_the_file_and_its_bytes(
    api: TestClient, batch_id: int, storage_dir: str, engine: Engine
) -> None:
    file = upload(api, batch_id)

    response = api.delete(f"/files/{file['ref_no']}")

    assert response.status_code == 204
    assert api.get(f"/files/{file['id']}").status_code == 404
    assert count(engine, "SELECT count(*) FROM files") == 0
    assert stored(storage_dir) == []  # also nothing left behind in .tmp


def test_delete_removes_runs_receipts_items_and_flags(
    api: TestClient, batch_id: int, engine: Engine
) -> None:
    file = upload(api, batch_id)
    with engine.begin() as connection:
        run_id = connection.execute(
            text(
                "INSERT INTO extraction_runs (file_id, parser, provider, model, ai_approved_by,"
                " ai_approved_at, accepted, result_json, finished_at) VALUES (:f, 'ai',"
                " 'anthropic', 'claude', 'local user', now(), true, '[]', now()) RETURNING id"
            ),
            {"f": file["id"]},
        ).scalar_one()
        vendor_id = connection.execute(
            text("INSERT INTO vendors (raw_name, normalized_name) VALUES ('X', 'X') RETURNING id")
        ).scalar_one()
        receipt_id = connection.execute(
            text(
                "INSERT INTO receipts (file_id, run_id, seq, ref_no, vendor_id, receipt_date,"
                " total) VALUES (:f, :r, 1, :ref, :v, '2026-08-14', 10) RETURNING id"
            ),
            {"f": file["id"], "r": run_id, "ref": file["ref_no"] + "-01", "v": vendor_id},
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO line_items (receipt_id, position, description, amount)"
                " VALUES (:r, 1, 'Room', 10)"
            ),
            {"r": receipt_id},
        )
        connection.execute(
            text(
                "INSERT INTO flags (file_id, receipt_id, type, severity, detail, dedupe_key)"
                " VALUES (:f, :r, 'validation_failed', 'warning', 'x', 'k')"
            ),
            {"f": file["id"], "r": receipt_id},
        )

    assert api.delete(f"/files/{file['id']}").status_code == 204

    for table in ("files", "extraction_runs", "receipts", "line_items", "flags"):
        assert count(engine, f"SELECT count(*) FROM {table}") == 0, table
    assert count(engine, "SELECT count(*) FROM vendors") == 1  # vendors are shared, kept


def test_deleting_an_original_promotes_its_earliest_copy(
    api: TestClient, batch_id: int, storage_dir: str
) -> None:
    original = upload(api, batch_id)
    first_copy = upload(api, batch_id, confirm=True)
    second_copy = upload(api, batch_id, confirm=True)

    assert api.delete(f"/files/{original['id']}").status_code == 204

    assert api.get(f"/files/{first_copy['id']}").json()["duplicate_of"] is None
    assert api.get(f"/files/{second_copy['id']}").json()["duplicate_of"]["id"] == first_copy["id"]
    assert len(stored(storage_dir)) == 1  # the copies still use the bytes
    assert api.get(f"/files/{first_copy['id']}/download").content == PDF


def test_deleting_the_last_holder_removes_the_bytes(
    api: TestClient, batch_id: int, storage_dir: str
) -> None:
    original = upload(api, batch_id)
    copy = upload(api, batch_id, confirm=True)

    api.delete(f"/files/{copy['id']}")
    assert len(stored(storage_dir)) == 1
    api.delete(f"/files/{original['id']}")
    assert stored(storage_dir) == []


def test_after_deleting_the_same_file_uploads_as_new(api: TestClient, batch_id: int) -> None:
    file = upload(api, batch_id)
    api.delete(f"/files/{file['id']}")

    response = api.post(
        f"/batches/{batch_id}/files", files={"file": ("bill.pdf", PDF, "application/pdf")}
    )
    assert response.status_code == 201
    assert response.json()["file"]["duplicate_of"] is None


@pytest.mark.parametrize("busy", ["processing", "ai_processing"])
def test_a_file_being_processed_cannot_be_deleted(
    api: TestClient, batch_id: int, engine: Engine, storage_dir: str, busy: str
) -> None:
    file = upload(api, batch_id)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE files SET status = :s WHERE id = :id"), {"s": busy, "id": file["id"]}
        )

    response = api.delete(f"/files/{file['id']}")

    assert response.status_code == 409
    assert response.json()["code"] == "file_busy"
    assert count(engine, "SELECT count(*) FROM files") == 1
    assert len(stored(storage_dir)) == 1


def test_deleting_a_missing_file_is_404(api: TestClient) -> None:
    assert api.delete("/files/999999").status_code == 404
    assert api.delete("/files/REF-2026-999999").json()["code"] == "file_not_found"
