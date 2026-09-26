"""Digital PDFs (real text on the page) with pdfplumber.

Pages are grouped into receipts by content (D-022); fields are read from the text with
labels, and line items from the tables pdfplumber finds, or from text tables.
"""

import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pdfplumber

from parchi.db.enums import FileKind, RunParser
from parchi.extraction.base import UnreadableFileError
from parchi.extraction.grid import confidence_of, find_items_table
from parchi.extraction.labels import FIELD_LABELS, is_document_title, match_label
from parchi.extraction.normalize import (
    DATE_PATTERN,
    amounts_in,
    clean_receipt_number,
    clean_vendor,
    find_date,
)
from parchi.extraction.text_table import read_text_table
from parchi.schemas.receipt import LineItemSchema, ReceiptSchema

# A page starts a new receipt if one of its first lines is a document title.
TITLE_SEARCH_LINES = 4
VENDOR_SEARCH_LINES = 5


def _label_regex(labels: list[str]) -> str:
    alternatives = sorted(labels, key=len, reverse=True)
    return "|".join(
        r"\W*".join(re.escape(word) for word in label.split()) for label in alternatives
    )


_NUMBER_LABEL = _label_regex(FIELD_LABELS["receipt_number"])
_NUMBER = re.compile(
    # (?![A-Za-z]) instead of \b, so labels ending in "#" ("Bill #") still match.
    rf"\b(?:{_NUMBER_LABEL})(?![A-Za-z])\W*?([A-Za-z0-9][A-Za-z0-9/\-]*\d[A-Za-z0-9/\-]*|\d+)",
    re.IGNORECASE,
)
# One pattern per date label, strongest first: "Invoice Date" beats "Order Date" or "Date".
_DATES = [
    re.compile(rf"\b{_label_regex([label])}(?![A-Za-z])\W*?({DATE_PATTERN})", re.IGNORECASE)
    for label in FIELD_LABELS["receipt_date"]
]


@dataclass
class Page:
    number: int
    text: str
    tables: list[list[list[str | None]]]

    @property
    def lines(self) -> list[str]:
        return [line.strip() for line in self.text.splitlines() if line.strip()]


def starts_receipt(page: Page) -> bool:
    """D-022: a receipt number, or a document title near the top, starts a new receipt."""
    if _NUMBER.search(page.text):
        return True
    return any(is_document_title(line) for line in page.lines[:TITLE_SEARCH_LINES])


def group_pages(pages: list[Page]) -> list[list[Page]]:
    groups: list[list[Page]] = []
    for page in pages:
        if not groups or starts_receipt(page):
            groups.append([page])
        else:
            groups[-1].append(page)
    return groups


def _vendor(lines: list[str]) -> str | None:
    for line in lines:
        match = match_label(line)
        if match and match.field == "vendor" and match.rest:
            return clean_vendor(match.rest)
    for line in lines[:VENDOR_SEARCH_LINES]:
        if is_document_title(line) or match_label(line) is not None:
            continue
        lowered = line.lower()
        if "gstin" in lowered or sum(ch.isdigit() for ch in line) > len(line) / 3:
            continue
        return clean_vendor(line)
    return None


def read_group(pages: list[Page]) -> ReceiptSchema | None:
    text = "\n".join(page.text for page in pages)
    lines = [line for page in pages for line in page.lines]

    number_match = _NUMBER.search(text)
    date_match = next((m for pattern in _DATES if (m := pattern.search(text))), None)
    receipt_date = find_date(date_match.group(1)) if date_match else find_date(text)

    best: dict[str, tuple[int, Decimal]] = {}
    tax_parts: dict[str, Decimal] = {}
    for line in lines:
        match = match_label(line)
        if match is None or match.field not in {"total", "subtotal", "tax", "tax_part"}:
            continue
        amounts = amounts_in(match.rest)
        if not amounts:
            continue
        amount = amounts[-1]  # "CGST @ 9% 45.00" or "Total 2 items 590.00": the last one
        if match.field == "tax_part":
            tax_parts.setdefault(match.label, amount)
        elif match.field not in best or match.priority < best[match.field][0]:
            best[match.field] = (match.priority, amount)

    items: list[LineItemSchema] = []
    for page in pages:
        for table in page.tables:
            found = find_items_table(table)
            if found:
                items.extend(found.items)

    # Items tables printed as text, without ruled lines; their Total row also gives the
    # taxable value and the tax when those are not printed on their own lines.
    text_table = None if items else read_text_table(lines)
    if text_table:
        items = text_table.items

    tax = best["tax"][1] if "tax" in best else None
    if tax is None and text_table and text_table.tax is not None:
        tax = text_table.tax
    if tax is None and tax_parts:
        tax = sum(tax_parts.values(), Decimal("0"))
    subtotal = best["subtotal"][1] if "subtotal" in best else None
    if subtotal is None and text_table:
        subtotal = text_table.subtotal
    total = best["total"][1] if "total" in best else None
    if total is None and text_table:
        total = text_table.total

    fields = {
        "vendor": _vendor(lines),
        "receipt_number": clean_receipt_number(number_match.group(1)) if number_match else None,
        "receipt_date": receipt_date,
        "subtotal": subtotal,
        "tax": tax,
        "total": total,
        "line_items": items,
    }
    if not (fields["total"] or fields["line_items"] or fields["receipt_number"]):
        return None
    first, last = pages[0].number, pages[-1].number
    source = f"page {first}" if first == last else f"pages {first}-{last}"
    return ReceiptSchema(**fields, confidence=confidence_of(fields), source=source)


def read_pages(path: Path) -> list[Page]:
    try:
        with pdfplumber.open(path) as pdf:
            return [
                Page(number=index, text=page.extract_text() or "", tables=page.extract_tables())
                for index, page in enumerate(pdf.pages, start=1)
            ]
    except Exception as exc:  # corrupt or password-protected
        raise UnreadableFileError(f"The PDF cannot be opened ({type(exc).__name__}).") from exc


class PdfTextExtractor:
    handles = frozenset({FileKind.PDF_TEXT})
    parser = RunParser.PDF_TEXT

    def extract(self, path: Path) -> list[ReceiptSchema]:
        receipts = []
        for group in group_pages(read_pages(path)):
            if receipt := read_group(group):
                receipts.append(receipt)
        return receipts
