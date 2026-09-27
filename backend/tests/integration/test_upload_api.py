"""Phase 2: upload, register, duplicates, the Files list and downloads, on a real database."""

import hashlib
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from tests.integration.conftest import log_in

pytestmark = pytest.mark.db

PDF = b"%PDF-1.4 fuel bill 1234.50" * 50
YEAR = datetime.now(ZoneInfo("Asia/Kolkata")).year


def new_batch(api: TestClient) -> int:
    response = api.post("/batches")
    assert response.status_code == 201
    return response.json()["id"]


def upload(
    api: TestClient,
    batch_id: int,
    name: str = "inv_0421.pdf",
    data: bytes = PDF,
    confirm_duplicate: bool = False,
):
    return api.post(
        f"/batches/{batch_id}/files",
        files={"file": (name, data, "application/octet-stream")},
        data={"confirm_duplicate": "true" if confirm_duplicate else "false"},
    )


def stored_files(storage_dir: str) -> list[Path]:
    return [p for p in Path(storage_dir).rglob("*") if p.is_file() and ".tmp" not in p.parts]


# --- register ------------------------------------------------------------------------


def test_upload_registers_the_file(api: TestClient, storage_dir: str) -> None:
    batch_id = new_batch(api)
    response = upload(api, batch_id)

    assert response.status_code == 201
    body = response.json()
    assert body["result"] == "registered"
    file = body["file"]
    assert file["ref_no"] == f"REF-{YEAR}-000001"
    assert file["original_name"] == "inv_0421.pdf"
    assert file["size_bytes"] == len(PDF)
    assert file["status"] == "pending"
    assert file["duplicate_of"] is None

    sha = hashlib.sha256(PDF).hexdigest()
    assert [p.name for p in stored_files(storage_dir)] == [f"{sha}.pdf"]
    assert "storage_path" not in file  # never exposed (hard rule 4)


def test_reference_numbers_count_up(api: TestClient) -> None:
    batch_id = new_batch(api)
    refs = [
        upload(api, batch_id, name=f"r{i}.pdf", data=PDF + bytes([i])).json()["file"]["ref_no"]
        for i in range(3)
    ]
    assert refs == [f"REF-{YEAR}-00000{i}" for i in (1, 2, 3)]


# --- duplicates (the phase 2 exit check, D-006 and D-015) ----------------------------


def test_same_file_twice_gives_one_file_and_a_duplicate_answer(
    api: TestClient, storage_dir: str, engine: Engine
) -> None:
    batch_id = new_batch(api)
    first = upload(api, batch_id).json()["file"]

    second = upload(api, batch_id, name="inv_0421_copy.pdf")

    assert second.status_code == 200
    assert second.json() == {
        "result": "duplicate",
        "duplicate_of": {
            "id": first["id"],
            "ref_no": first["ref_no"],
            "original_name": "inv_0421.pdf",
        },
    }
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM files")).scalar_one() == 1
    assert len(stored_files(storage_dir)) == 1


def test_confirmed_duplicate_is_saved_and_linked_to_the_original(
    api: TestClient, storage_dir: str
) -> None:
    batch_id = new_batch(api)
    original = upload(api, batch_id).json()["file"]

    response = upload(api, batch_id, name="inv_0421_copy.pdf", confirm_duplicate=True)

    assert response.status_code == 201
    copy = response.json()["file"]
    assert copy["ref_no"] == f"REF-{YEAR}-000002"
    assert copy["status"] == "pending"
    assert copy["duplicate_of"]["ref_no"] == original["ref_no"]
    assert len(stored_files(storage_dir)) == 1  # the bytes are shared, not stored twice


def test_a_third_copy_links_to_the_earliest_file(api: TestClient) -> None:
    batch_id = new_batch(api)
    original = upload(api, batch_id).json()["file"]
    upload(api, batch_id, confirm_duplicate=True)

    third = upload(api, batch_id, confirm_duplicate=True).json()["file"]
    assert third["duplicate_of"]["id"] == original["id"]


def test_simultaneous_identical_uploads_save_only_one(
    api: TestClient, migrated: str, engine: Engine
) -> None:
    """D-018: the advisory lock makes the second one a duplicate, whatever the timing."""
    batch_id = new_batch(api)
    barrier = threading.Barrier(2)
    results: list[dict] = []

    def worker() -> None:
        import asyncio
        import sys

        from parchi.api.main import create_app

        options = {"loop_factory": asyncio.SelectorEventLoop} if sys.platform == "win32" else {}
        with TestClient(create_app(), backend_options=options) as client:
            log_in(client, "reviewer")
            barrier.wait()
            results.append(upload(client, batch_id, data=b"same bytes" * 1000).json())

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert sorted(r["result"] for r in results) == ["duplicate", "registered"]
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM files")).scalar_one() == 1


# --- what receive refuses ------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "status", "code"),
    [
        ("setup.exe", 415, "unsupported_type"),
        ("notes", 415, "unsupported_type"),
        ("..\\evil.pdf", 422, "invalid_name"),
        ("bill‮.pdf", 422, "invalid_name"),
    ],
)
def test_bad_uploads_are_refused_and_nothing_is_stored(
    api: TestClient, storage_dir: str, name: str, status: int, code: str
) -> None:
    batch_id = new_batch(api)
    response = upload(api, batch_id, name=name)
    assert response.status_code == status
    assert response.json()["code"] == code
    assert stored_files(storage_dir) == []


def test_too_large_file_is_refused(api: TestClient, storage_dir: str, monkeypatch) -> None:
    from parchi.config import get_settings

    monkeypatch.setattr(get_settings(), "max_upload_mb", 1)
    batch_id = new_batch(api)
    response = upload(api, batch_id, data=b"x" * (1024 * 1024 + 1))
    assert response.status_code == 413
    assert response.json()["code"] == "file_too_large"
    assert stored_files(storage_dir) == []
    assert list((Path(storage_dir) / ".tmp").iterdir()) == []


def test_a_full_batch_refuses_more_files(api: TestClient, monkeypatch) -> None:
    from parchi.config import get_settings

    monkeypatch.setattr(get_settings(), "max_files_per_batch", 2)
    batch_id = new_batch(api)
    assert upload(api, batch_id, data=b"1" * 10, name="a.pdf").status_code == 201
    assert upload(api, batch_id, data=b"2" * 10, name="b.pdf").status_code == 201

    response = upload(api, batch_id, data=b"3" * 10, name="c.pdf")
    assert response.status_code == 409
    assert response.json()["code"] == "batch_full"


def test_upload_to_a_missing_batch_is_refused(api: TestClient) -> None:
    response = upload(api, 999_999)
    assert response.status_code == 404
    assert response.json()["code"] == "batch_not_found"


# --- batches, the Files list and downloads -------------------------------------------


def test_batch_lists_its_files(api: TestClient) -> None:
    batch_id = new_batch(api)
    upload(api, batch_id, name="a.pdf", data=b"a" * 10)
    upload(api, batch_id, name="b.csv", data=b"b" * 10)

    body = api.get(f"/batches/{batch_id}").json()
    assert [f["original_name"] for f in body["files"]] == ["a.pdf", "b.csv"]
    assert api.get("/batches/999999").status_code == 404


def test_files_list_filters_searches_and_pages(api: TestClient) -> None:
    batch_id = new_batch(api)
    for i, name in enumerate(["fuel_aug.pdf", "hotel.jpg", "fuel_sep.pdf", "tea_50%.png"]):
        upload(api, batch_id, name=name, data=bytes([i]) * 10)

    everything = api.get("/files").json()
    assert everything["total"] == 4
    assert everything["items"][0]["original_name"] == "tea_50%.png"  # newest first

    assert api.get("/files", params={"q": "FUEL"}).json()["total"] == 2
    assert (
        api.get("/files", params={"q": f"REF-{YEAR}-000002"}).json()["items"][0]["original_name"]
        == "hotel.jpg"
    )
    assert api.get("/files", params={"q": "%"}).json()["total"] == 1  # % is literal, not a wildcard
    assert api.get("/files", params={"status": "pending"}).json()["total"] == 4
    assert api.get("/files", params={"status": "parsed"}).json()["total"] == 0

    page = api.get("/files", params={"page": 2, "page_size": 3}).json()
    assert (page["total"], len(page["items"]), page["page"]) == (4, 1, 2)


def test_a_file_is_found_by_id_or_reference(api: TestClient) -> None:
    batch_id = new_batch(api)
    file = upload(api, batch_id).json()["file"]

    assert api.get(f"/files/{file['id']}").json()["ref_no"] == file["ref_no"]
    assert api.get(f"/files/{file['ref_no']}").json()["id"] == file["id"]
    for key in ("999999", "REF-2026-999999", "not-a-key"):
        assert api.get(f"/files/{key}").status_code == 404


def test_download_returns_the_original_bytes_and_name(api: TestClient) -> None:
    batch_id = new_batch(api)
    file = upload(api, batch_id, name="चाय bill.pdf").json()["file"]

    response = api.get(f"/files/{file['ref_no']}/download")
    assert response.status_code == 200
    assert response.content == PDF
    assert response.headers["content-type"] == "application/pdf"
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert "filename*=utf-8''%E0%A4%9A" in disposition
