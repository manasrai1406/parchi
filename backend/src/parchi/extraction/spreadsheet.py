"""Excel and CSV receipts: one form-style receipt per sheet (D-021)."""

import csv
import io
import math
import re
from pathlib import Path
from typing import Any

import pandas as pd

from parchi.db.enums import FileKind, RunParser
from parchi.extraction.base import UnreadableFileError
from parchi.extraction.grid import Grid, read_receipt
from parchi.schemas.receipt import ReceiptSchema

XLS_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
CSV_ENCODINGS = ("utf-8-sig", "cp1252")
CSV_DELIMITERS = ",;\t|"


def _cell(value: Any) -> Any:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if value is pd.NaT:
        return None
    return value


def _trim(grid: Grid) -> Grid:
    """Drop trailing empty rows and columns (sheets often carry formatting far below)."""
    rows = [list(row) for row in grid]
    while rows and all(cell is None for cell in rows[-1]):
        rows.pop()
    width = max((i + 1 for row in rows for i, c in enumerate(row) if c is not None), default=0)
    return [row[:width] for row in rows]


class ExcelExtractor:
    handles = frozenset({FileKind.EXCEL})
    parser = RunParser.EXCEL

    def extract(self, path: Path) -> list[ReceiptSchema]:
        # The engine follows the bytes, not the name: a .xlsx may really be a .xls.
        with path.open("rb") as handle:
            engine = "xlrd" if handle.read(8) == XLS_SIGNATURE else "openpyxl"
        try:
            sheets = pd.read_excel(path, sheet_name=None, header=None, dtype=object, engine=engine)
        except Exception as exc:  # corrupt, encrypted, or not a workbook at all
            reason = f"The workbook cannot be opened ({type(exc).__name__})."
            raise UnreadableFileError(reason) from exc

        receipts = []
        for name, frame in sheets.items():
            grid = _trim([[_cell(value) for value in row] for row in frame.itertuples(index=False)])
            if receipt := read_receipt(grid, source=f"sheet: {name}"):
                receipts.append(receipt)
        return receipts


def read_csv_grid(data: bytes) -> Grid:
    for encoding in CSV_ENCODINGS:
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise UnreadableFileError("The CSV file's text encoding is not recognised.")

    rows = list(csv.reader(io.StringIO(text), delimiter=pick_delimiter(text[:8192])))
    return _trim([[cell if cell.strip() else None for cell in row] for row in rows])


# A comma between digits is a thousands separator (6,000.00 or 1,23,456), not a delimiter.
_DIGIT_COMMA = re.compile(r"(?<=\d),(?=\d)")


def pick_delimiter(sample: str) -> str:
    """The delimiter found on the most lines. csv.Sniffer is fooled by amounts like 6,000.00
    and by receipts whose rows have different numbers of cells."""
    lines = [line for line in sample.splitlines() if line.strip()]

    def lines_with(delimiter: str) -> int:
        if delimiter == ",":
            return sum("," in _DIGIT_COMMA.sub("", line) for line in lines)
        return sum(delimiter in line for line in lines)

    return max(CSV_DELIMITERS, key=lines_with)


class CsvExtractor:
    handles = frozenset({FileKind.CSV})
    parser = RunParser.CSV

    def extract(self, path: Path) -> list[ReceiptSchema]:
        data = path.read_bytes()
        if not data.strip():
            raise UnreadableFileError("The CSV file is empty.")
        receipt = read_receipt(read_csv_grid(data), source="csv")
        return [receipt] if receipt else []
