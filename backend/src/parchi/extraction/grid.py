"""Read one form-style receipt from a grid of cells (D-021).

A grid is rows of cells: a spreadsheet sheet, a CSV, or a table found in a PDF.
Labels ("Invoice No", "Grand Total") are matched and their value taken from the
same cell ("Date: 14/08/2026"), the next filled cell to the right, or the cell below.
An items table is found by its header row.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from parchi.extraction.labels import ITEM_HEADERS, is_document_title, match_label
from parchi.extraction.normalize import (
    clean_receipt_number,
    clean_text,
    clean_vendor,
    parse_amount,
    parse_date,
    parse_quantity,
)
from parchi.schemas.receipt import LineItemSchema, ReceiptSchema

Cell = Any
Grid = list[list[Cell]]

# How far to the right of a label to look for its value.
MAX_VALUE_DISTANCE = 4
# Vendor names without a label are looked for in the first rows only.
VENDOR_SEARCH_ROWS = 6

# Share of the confidence each found field contributes.
CONFIDENCE_WEIGHTS = {
    "vendor": 0.2,
    "receipt_date": 0.2,
    "total": 0.3,
    "receipt_number": 0.15,
    "line_items": 0.15,
}


def _is_empty(cell: Cell) -> bool:
    return clean_text(cell) is None


def _text(cell: Cell) -> str:
    return clean_text(cell) or ""


@dataclass
class ItemsTable:
    header_row: int
    last_row: int
    items: list[LineItemSchema]


def _match_header(cell: Cell) -> str | None:
    """Which items-table column a header cell names, if any."""
    text = _text(cell).lower().strip(" .:()#")
    for column, names in ITEM_HEADERS.items():
        if text in names:
            return column
    return None


def _cell_at(row: list[Cell], columns: dict[str, int], column: str) -> Cell:
    index = columns.get(column)
    return row[index] if index is not None and index < len(row) else None


def find_items_table(grid: Grid) -> ItemsTable | None:
    for row_index, row in enumerate(grid):
        columns: dict[str, int] = {}
        for col_index, cell in enumerate(row):
            name = _match_header(cell)
            if name and name not in columns:
                columns[name] = col_index
        if "description" not in columns or "amount" not in columns:
            continue

        items: list[LineItemSchema] = []
        last_row = row_index
        for item_row in grid[row_index + 1 :]:
            if all(_is_empty(cell) for cell in item_row):
                break
            # The table ends where the totals start.
            labels = [match_label(_text(cell)) for cell in item_row if not _is_empty(cell)]
            if any(m and m.field in {"total", "subtotal", "tax", "tax_part"} for m in labels):
                break
            last_row += 1

            description = clean_text(_cell_at(item_row, columns, "description"))
            amount = parse_amount(_cell_at(item_row, columns, "amount"))
            if description is None or amount is None:
                continue  # a sub-heading or a blank spacer inside the table
            items.append(
                LineItemSchema(
                    description=description,
                    quantity=parse_quantity(_cell_at(item_row, columns, "quantity")),
                    unit_price=parse_amount(_cell_at(item_row, columns, "unit_price")),
                    amount=amount,
                )
            )
        return ItemsTable(header_row=row_index, last_row=last_row, items=items)
    return None


def _value_for(grid: Grid, row: int, col: int, rest: str) -> Cell | None:
    """The value of a label: in the same cell, to its right, or below it."""
    if rest:
        return rest
    cells = grid[row]
    for right in cells[col + 1 : col + 1 + MAX_VALUE_DISTANCE]:
        if not _is_empty(right):
            # Another label next to this one means this label's value is missing.
            if isinstance(right, str) and match_label(right) is not None:
                break
            return right
    if row + 1 < len(grid) and col < len(grid[row + 1]):
        below = grid[row + 1][col]
        if not _is_empty(below) and match_label(_text(below)) is None:
            return below
    return None


@dataclass
class _Found:
    """The best value seen so far for each field, with the label priority it came from."""

    values: dict[str, tuple[int, Any]] = field(default_factory=dict)
    tax_parts: dict[str, Decimal] = field(default_factory=dict)

    def offer(self, name: str, priority: int, value: Any) -> None:
        if value is None:
            return
        current = self.values.get(name)
        if current is None or priority < current[0]:
            self.values[name] = (priority, value)

    def get(self, name: str) -> Any:
        found = self.values.get(name)
        return found[1] if found else None


PARSERS = {
    "receipt_number": clean_receipt_number,
    "receipt_date": parse_date,
    "vendor": clean_vendor,
    "total": parse_amount,
    "subtotal": parse_amount,
    "tax": parse_amount,
}


def _fallback_vendor(grid: Grid) -> str | None:
    """The first plain text near the top that is not a label, a title or a number."""
    for row in grid[:VENDOR_SEARCH_ROWS]:
        for cell in row:
            text = clean_text(cell)
            if text is None or isinstance(cell, int | float | Decimal):
                continue
            if is_document_title(text) or match_label(text) is not None:
                continue
            if "gstin" in text.lower() or sum(ch.isdigit() for ch in text) > len(text) / 3:
                continue
            return clean_vendor(text)
    return None


def confidence_of(receipt_fields: dict[str, Any]) -> float:
    score = sum(weight for name, weight in CONFIDENCE_WEIGHTS.items() if receipt_fields.get(name))
    return round(min(score, 1.0), 3)


def read_receipt(grid: Grid, source: str) -> ReceiptSchema | None:
    """One receipt from a grid, or None if the grid does not look like a receipt."""
    table = find_items_table(grid)
    found = _Found()

    for row_index, row in enumerate(grid):
        if table and table.header_row <= row_index <= table.last_row:
            continue
        for col_index, cell in enumerate(row):
            text = clean_text(cell)
            if text is None or isinstance(cell, int | float | Decimal) or is_document_title(text):
                continue
            match = match_label(text)
            if match is None:
                continue
            parse = parse_amount if match.field == "tax_part" else PARSERS[match.field]
            # Text after the label may be a note ("CGST @ 9%"), not the value: then the
            # value is in a neighbouring cell.
            parsed = parse(match.rest) if match.rest else None
            if parsed is None:
                parsed = parse(_value_for(grid, row_index, col_index, rest=""))
            if match.field == "tax_part":
                if parsed is not None:
                    found.tax_parts.setdefault(match.label, parsed)
                continue
            found.offer(match.field, match.priority, parsed)

    tax = found.get("tax")
    if tax is None and found.tax_parts:
        tax = sum(found.tax_parts.values(), Decimal("0"))

    fields = {
        "vendor": found.get("vendor") or _fallback_vendor(grid),
        "receipt_number": found.get("receipt_number"),
        "receipt_date": found.get("receipt_date"),
        "subtotal": found.get("subtotal"),
        "tax": tax,
        "total": found.get("total"),
        "line_items": table.items if table else [],
    }
    if not (fields["total"] or fields["line_items"] or fields["receipt_number"]):
        return None
    return ReceiptSchema(
        **fields, confidence=confidence_of(fields), source=source, text=grid_text(grid)
    )


def grid_text(grid: Grid) -> str:
    """The sheet as lines of text, a row per line, for learning labels (D-048)."""
    rows = (" ".join(str(cell) for cell in row if clean_text(cell) is not None) for row in grid)
    return "\n".join(row for row in rows if row)
