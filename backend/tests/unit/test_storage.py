import hashlib
import io
from pathlib import Path

import pytest

from parchi.ingestion.storage import FileTooLargeError, Storage

DATA = b"%PDF-1.4 receipt bytes" * 1000
SHA = hashlib.sha256(DATA).hexdigest()


@pytest.fixture
def storage(tmp_path: Path) -> Storage:
    return Storage(tmp_path / "uploads")


def leftover_temp_files(storage: Storage) -> list[Path]:
    return list(storage.tmp_dir.iterdir())


def test_receive_hashes_and_counts(storage: Storage) -> None:
    received = storage.receive(io.BytesIO(DATA), max_bytes=len(DATA))
    assert received.sha256 == SHA
    assert received.size_bytes == len(DATA)
    assert received.tmp_path.read_bytes() == DATA


def test_receive_refuses_too_large_and_leaves_nothing(storage: Storage) -> None:
    with pytest.raises(FileTooLargeError):
        storage.receive(io.BytesIO(DATA), max_bytes=len(DATA) - 1)
    assert leftover_temp_files(storage) == []


def test_store_puts_the_file_under_its_hash(storage: Storage) -> None:
    received = storage.receive(io.BytesIO(DATA), max_bytes=len(DATA))
    relative, newly_written = storage.store(received, "pdf")

    assert relative == f"{SHA[:2]}/{SHA}.pdf"
    assert newly_written is True
    assert storage.absolute_path(relative).read_bytes() == DATA
    assert leftover_temp_files(storage) == []


def test_storing_identical_bytes_again_keeps_the_first_copy(storage: Storage) -> None:
    first = storage.receive(io.BytesIO(DATA), max_bytes=len(DATA))
    relative, _ = storage.store(first, "pdf")
    second = storage.receive(io.BytesIO(DATA), max_bytes=len(DATA))

    again, newly_written = storage.store(second, "pdf")

    assert again == relative
    assert newly_written is False
    assert leftover_temp_files(storage) == []


@pytest.mark.parametrize("relative", ["../outside.pdf", "/etc/passwd", ".tmp/upload-123"])
def test_paths_outside_storage_are_refused(storage: Storage, relative: str) -> None:
    storage.ensure_dirs()
    with pytest.raises(ValueError):
        storage.absolute_path(relative)


def test_set_aside_and_put_back_restore_the_file(storage: Storage) -> None:
    received = storage.receive(io.BytesIO(DATA), max_bytes=len(DATA))
    relative, _ = storage.store(received, "pdf")

    aside = storage.set_aside(relative)
    assert aside is not None
    assert not storage.absolute_path(relative).exists()

    storage.put_back(aside, relative)
    assert storage.absolute_path(relative).read_bytes() == DATA


def test_set_aside_of_a_missing_file_is_none(storage: Storage) -> None:
    assert storage.set_aside(f"{SHA[:2]}/{SHA}.pdf") is None
