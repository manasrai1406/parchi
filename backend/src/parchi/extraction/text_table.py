"""Items tables printed as plain text, without ruled lines.

Many invoices (marketplace and billing-software PDFs) print their items as text:

    Product Title  Qty  Gross  Discounts  Taxable  SGST  CGST  Total
    Wireless earbuds  1  3799.00  0.00  3219.50  289.75  289.75  3799.00
    Total  1  3799.00  0.00  3219.50  289.75  289.75  3799.00

The header row names the numeric columns in order; a row is an item when it ends with
exactly that many numbers. The "Total" row gives the subtotal (taxable value), the tax
(SGST + CGST + IGST ...) and the total.
"""

import re
from dataclasses import dataclass, field
from decimal import Decimal

from parchi.extraction.labels import match_label
from parchi.extraction.normalize import parse_amount, parse_quantity
from parchi.schemas.receipt import LineItemSchema

NUMBER_TOKEN = re.compile(r"^\(?-?(?:\d{1,3}(?:,\d{2,3})+|\d+)(?:\.\d+)?\)?$")

# First word of a header -> what its column holds.
COLUMN_WORDS = {
    "qty": "quantity",
    "quantity": "quantity",
    "qnty": "quantity",
    "nos": "quantity",
    "rate": "unit_price",
    "price": "unit_price",
    "mrp": "unit_price",
    "gross": "gross",
    "discount": "discount",
    "discounts": "discount",
    "taxable": "taxable",
    "sgst": "tax",
    "cgst": "tax",
    "igst": "tax",
    "utgst": "tax",
    "cess": "tax",
    "gst": "tax",
    "tax": "tax",
    "total": "amount",
    "amount": "amount",
    "amt": "amount",
    "value": "amount",
}
# Second words that belong to the header before them ("Gross Amount", "Taxable Value").
SUFFIX_WORDS = {"amount", "amt", "value"}
# Headers that can take one of those second words.
SUFFIX_HEADS = {"gross", "taxable", "discount", "tax", "amount"}
DESCRIPTION_WORDS = {"description", "item", "items", "particulars", "product", "details", "service"}
MAX_TABLE_LINES = 80


def _word(token: str) -> str:
    return token.lower().strip(".:₹()/#*")


def header_columns(tokens: list[str]) -> list[str] | None:
    """The numeric columns a header line names, in order; None if it is not a header."""
    words = [_word(token) for token in tokens]
    if not any(word in DESCRIPTION_WORDS for word in words):
        return None
    columns: list[str] = []
    can_take_suffix = False
    for word in words:
        kind = COLUMN_WORDS.get(word)
        if kind is None:
            can_take_suffix = False
            continue
        if can_take_suffix and word in SUFFIX_WORDS:
            can_take_suffix = False  # "Taxable Value" is one column; "... Value Amount" is two
            continue
        columns.append(kind)
        can_take_suffix = kind in SUFFIX_HEADS
    if "amount" not in columns or len(columns) < 2:
        return None
    return columns


@dataclass
class TextTable:
    items: list[LineItemSchema] = field(default_factory=list)
    subtotal: Decimal | None = None
    tax: Decimal | None = None
    total: Decimal | None = None


def _values(tokens: list[str], columns: list[str]) -> dict[str, list[str]] | None:
    """Map the trailing numbers of a row onto the columns, or None if they don't fit."""
    trailing = tokens[-len(columns) :]
    if len(tokens) < len(columns) or not all(NUMBER_TOKEN.match(t) for t in trailing):
        return None
    values: dict[str, list[str]] = {}
    for kind, token in zip(columns, trailing, strict=True):
        values.setdefault(kind, []).append(token)
    return values


def _sum(tokens: list[str] | None) -> Decimal | None:
    if not tokens:
        return None
    total = Decimal("0")
    for token in tokens:
        amount = parse_amount(token)
        if amount is None:
            return None
        total += amount
    return total


def _find_header(lines: list[str]) -> tuple[int, list[str]] | None:
    for index, line in enumerate(lines):
        if columns := header_columns(line.split()):
            return index, columns
    return None


def read_text_table(lines: list[str]) -> TextTable | None:
    header = _find_header(lines)
    if header is None:
        return None
    index, columns = header

    table = TextTable()
    for line in lines[index + 1 : index + 1 + MAX_TABLE_LINES]:
        tokens = line.split()
        label = match_label(line)
        if label and label.field in {"total", "subtotal"}:
            # The totals row ends the table.
            values = _values(tokens, columns)
            if values and label.field == "total":
                table.subtotal = _sum(values.get("taxable"))
                table.tax = _sum(values.get("tax"))
                table.total = parse_amount(values["amount"][-1])
            break
        values = _values(tokens, columns)
        if values is None or len(tokens) == len(columns):
            continue  # a wrapped description line, or a sub-heading
        amount = parse_amount(values["amount"][-1])
        if amount is None:
            continue
        table.items.append(
            LineItemSchema(
                description=" ".join(tokens[: -len(columns)]),
                quantity=parse_quantity(values["quantity"][0]) if "quantity" in values else None,
                unit_price=parse_amount(values["unit_price"][0])
                if "unit_price" in values
                else None,
                amount=amount,
            )
        )
    return table if table.items or table.total is not None else None
