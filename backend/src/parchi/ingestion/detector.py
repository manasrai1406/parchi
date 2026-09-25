"""Stage 3: identify a file's type from its bytes, never its name."""

import csv
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pdfplumber

from parchi.db.enums import FileKind
from parchi.extraction.base import UnreadableFileError

# A text PDF averages at least this many characters of real text per page.
MIN_TEXT_CHARS_PER_PAGE = 25
HEADER_BYTES = 16
SNIFF_BYTES = 8192


@dataclass(frozen=True)
class Detection:
    kind: FileKind
    mime_type: str


def _pdf(path: Path) -> Detection:
    try:
        with pdfplumber.open(path) as pdf:
            if not pdf.pages:
                raise UnreadableFileError("The PDF has no pages.")
            chars = sum(len(page.chars) for page in pdf.pages)
            pages = len(pdf.pages)
    except UnreadableFileError:
        raise
    except Exception as exc:  # corrupt, or password-protected
        raise UnreadableFileError(
            f"The PDF cannot be opened ({type(exc).__name__}). "
            "It may be damaged or password-protected."
        ) from exc
    kind = FileKind.PDF_TEXT if chars / pages >= MIN_TEXT_CHARS_PER_PAGE else FileKind.PDF_SCAN
    return Detection(kind, "application/pdf")


def _zip(path: Path) -> Detection:
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
    except zipfile.BadZipFile as exc:
        raise UnreadableFileError("The file is damaged.") from exc
    if "xl/workbook.xml" in names:
        return Detection(
            FileKind.EXCEL, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    raise UnreadableFileError("This is a zip archive, not a spreadsheet.")


def _looks_like_csv(data: bytes) -> bool:
    if b"\x00" in data[:4096]:
        return False
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            sample = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        return False
    lines = [line for line in sample.splitlines() if line.strip()]
    if len(lines) < 2:
        return False
    try:
        csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        # Receipt CSVs often have rows of different widths, which defeats the sniffer.
        return sum(any(d in line for d in ",;\t|") for line in lines) >= len(lines) / 2
    return True


def detect(path: Path) -> Detection:
    """What the file really is. Raises UnreadableFileError for anything we cannot open."""
    with path.open("rb") as handle:
        start = handle.read(SNIFF_BYTES)
    header = start[:HEADER_BYTES]
    if not header:
        raise UnreadableFileError("The file is empty.")

    if header.startswith(b"%PDF"):
        return _pdf(path)
    if header.startswith(b"PK\x03\x04"):
        return _zip(path)
    if header.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        # Legacy .xls, or an encrypted .xlsx (also an OLE container); the extractor tells.
        return Detection(FileKind.EXCEL, "application/vnd.ms-excel")
    if header.startswith(b"\xff\xd8\xff"):
        return Detection(FileKind.IMAGE, "image/jpeg")
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return Detection(FileKind.IMAGE, "image/png")
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return Detection(FileKind.IMAGE, "image/webp")
    if header[4:8] == b"ftyp" and header[8:12] in {b"heic", b"heix", b"mif1", b"msf1", b"hevc"}:
        return Detection(FileKind.IMAGE, "image/heic")
    if _looks_like_csv(start):
        return Detection(FileKind.CSV, "text/csv")
    raise UnreadableFileError("This file type is not supported.")
