"""What every extractor looks like (PLAN.md, stage 4)."""

from pathlib import Path
from typing import Protocol

from parchi.db.enums import FileKind, RunParser
from parchi.schemas.receipt import ReceiptSchema


class UnreadableFileError(Exception):
    """The bytes cannot be opened: corrupt, password-protected, or empty. Never retried."""


class Extractor(Protocol):
    handles: frozenset[FileKind]
    parser: RunParser

    def extract(self, path: Path) -> list[ReceiptSchema]:
        """Every receipt in the file. An empty list means none could be found."""
        ...
