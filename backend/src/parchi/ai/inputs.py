"""What is sent to the provider for a file (D-035): the original image or PDF, or the
text of a spreadsheet, which providers cannot read directly."""

import csv
import io
from pathlib import Path

from parchi.ai.base import AiCallError, AiInput
from parchi.db.enums import FileKind
from parchi.extraction.base import UnreadableFileError
from parchi.extraction.spreadsheet import XLS_SIGNATURE, read_csv_grid

IMAGE_TYPES = {b"\xff\xd8\xff": "image/jpeg", b"\x89PNG": "image/png"}
MAX_TEXT_CHARS = 200_000


def _image_type(header: bytes) -> str | None:
    for magic, media_type in IMAGE_TYPES.items():
        if header.startswith(magic):
            return media_type
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "image/webp"
    return None


def _grid_text(rows: list[list[object]]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    for row in rows:
        writer.writerow(["" if cell is None else str(cell) for cell in row])
    return out.getvalue()


def _spreadsheet_text(path: Path) -> str:
    import pandas as pd

    with path.open("rb") as handle:
        engine = "xlrd" if handle.read(8) == XLS_SIGNATURE else "openpyxl"
    try:
        sheets = pd.read_excel(path, sheet_name=None, header=None, dtype=object, engine=engine)
    except Exception as exc:
        raise AiCallError("The workbook cannot be opened.") from exc
    parts = []
    for name, frame in sheets.items():
        rows = [
            [None if value != value else value for value in row]
            for row in frame.itertuples(index=False)
        ]
        parts.append(f"Sheet: {name}\n{_grid_text(rows)}")
    return "\n".join(parts)


def build_input(path: Path, kind: FileKind | None, filename: str) -> AiInput:
    with path.open("rb") as handle:
        header = handle.read(16)
    if header.startswith(b"%PDF"):
        return AiInput(filename=filename, pdf=path.read_bytes())
    if media_type := _image_type(header):
        return AiInput(filename=filename, image=path.read_bytes(), image_type=media_type)
    if kind == FileKind.EXCEL:
        text = _spreadsheet_text(path)
    elif kind == FileKind.CSV:
        try:
            text = _grid_text(read_csv_grid(path.read_bytes()))
        except UnreadableFileError as exc:
            raise AiCallError(str(exc)) from exc
    elif kind == FileKind.IMAGE:
        raise AiCallError("HEIC photos can't be sent. Convert the photo to JPG or PNG first.")
    else:
        raise AiCallError("This file type can't be sent to an AI provider.")
    if len(text) > MAX_TEXT_CHARS:
        raise AiCallError("The spreadsheet is too large to send in one request.")
    return AiInput(filename=filename, text=text)
