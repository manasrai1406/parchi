"""Original files on disk, stored under their SHA-256 (hard rule 10).

Layout: <STORAGE_DIR>/<first two hash chars>/<hash>.<ext>. Uploads are first streamed
to <STORAGE_DIR>/.tmp and then renamed into place, so a stored file is always complete.
"""

import hashlib
import os
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO

CHUNK_SIZE = 1024 * 1024
TMP_DIR_NAME = ".tmp"


class FileTooLargeError(ValueError):
    pass


@dataclass(frozen=True)
class ReceivedFile:
    """An upload streamed to a temporary file, with its hash and size."""

    tmp_path: Path
    sha256: str
    size_bytes: int

    def discard(self) -> None:
        self.tmp_path.unlink(missing_ok=True)


class Storage:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    @property
    def tmp_dir(self) -> Path:
        return self.root / TMP_DIR_NAME

    def ensure_dirs(self) -> None:
        self.tmp_dir.mkdir(parents=True, exist_ok=True)

    def receive(self, source: BinaryIO, max_bytes: int) -> ReceivedFile:
        """Stream `source` to a temporary file, hashing it and enforcing the size limit."""
        self.ensure_dirs()
        digest = hashlib.sha256()
        size = 0
        fd, name = tempfile.mkstemp(dir=self.tmp_dir, prefix="upload-")
        tmp_path = Path(name)
        try:
            with os.fdopen(fd, "wb") as out:
                while chunk := source.read(CHUNK_SIZE):
                    size += len(chunk)
                    if size > max_bytes:
                        raise FileTooLargeError
                    digest.update(chunk)
                    out.write(chunk)
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise
        return ReceivedFile(tmp_path=tmp_path, sha256=digest.hexdigest(), size_bytes=size)

    @staticmethod
    def relative_path(sha256: str, ext: str) -> str:
        return str(PurePosixPath(sha256[:2]) / f"{sha256}.{ext}")

    def absolute_path(self, relative: str) -> Path:
        """Resolve a stored relative path, refusing anything outside the storage root."""
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root) or path.parent == self.tmp_dir:
            raise ValueError("Stored path is outside the storage directory")
        return path

    def store(self, received: ReceivedFile, ext: str) -> tuple[str, bool]:
        """Move the upload into place. Returns (relative path, whether it was newly written).

        Identical bytes already stored under the same name are kept; the upload is dropped.
        """
        relative = self.relative_path(received.sha256, ext)
        target = self.absolute_path(relative)
        if target.exists():
            received.discard()
            return relative, False
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(received.tmp_path, target)
        return relative, True

    def remove(self, relative: str) -> None:
        self.absolute_path(relative).unlink(missing_ok=True)

    def set_aside(self, relative: str) -> Path | None:
        """Move stored bytes out of place, so a delete can still be undone until it commits."""
        target = self.absolute_path(relative)
        if not target.exists():
            return None
        self.ensure_dirs()
        aside = self.tmp_dir / f"deleting-{uuid.uuid4().hex}-{target.name}"
        os.replace(target, aside)
        return aside

    def put_back(self, aside: Path, relative: str) -> None:
        os.replace(aside, self.absolute_path(relative))
