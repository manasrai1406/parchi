"""Words that label a receipt's fields, shared by the spreadsheet and PDF extractors.

Order matters inside a list: earlier labels win when a receipt prints several
(a "Grand Total" beats a plain "Total").
"""

import re
from dataclasses import dataclass

FIELD_LABELS: dict[str, list[str]] = {
    "receipt_number": [
        "invoice no",
        "invoice number",
        "invoice #",
        "inv no",
        "tax invoice no",
        "bill no",
        "bill number",
        "bill #",
        "receipt no",
        "receipt number",
        "receipt #",
        "voucher no",
        "memo no",
        "cash memo no",
        "txn no",
        "transaction no",
    ],
    "receipt_date": [
        "invoice date",
        "bill date",
        "receipt date",
        "txn date",
        "transaction date",
        "dated",
        "date",
    ],
    "vendor": [
        "vendor name",
        "supplier name",
        "vendor",
        "supplier",
        "seller",
        "sold by",
        "billed by",
        "merchant",
        "shop name",
        "store name",
        "company name",
    ],
    "total": [
        "grand total",
        "total amount payable",
        "net amount payable",
        "amount payable",
        "net payable",
        "total payable",
        "invoice total",
        "invoice value",
        "bill amount",
        "total amount",
        "net amount",
        "amount due",
        "total due",
        "total",
    ],
    "subtotal": [
        "sub total",
        "subtotal",
        "taxable value",
        "taxable amount",
        "total before tax",
        "amount before tax",
    ],
    "tax": ["total gst", "total tax", "gst amount", "tax amount", "total tax amount", "gst", "tax"],
    # Parts of the tax, added up when no overall tax line is printed.
    "tax_part": ["cgst", "sgst", "utgst", "igst", "cess", "vat"],
}

# Headers of an items table.
ITEM_HEADERS: dict[str, list[str]] = {
    "description": [
        "description",
        "item description",
        "item name",
        "item",
        "items",
        "particulars",
        "product",
        "details",
        "service",
    ],
    "quantity": ["qty", "quantity", "qnty", "nos", "units"],
    "unit_price": ["rate", "unit price", "price", "mrp", "unit rate", "rate per unit"],
    "amount": ["amount", "amt", "total", "value", "line total", "net amount"],
}

# Document titles, never vendor names.
DOCUMENT_TITLES = {
    "tax invoice",
    "invoice",
    "retail invoice",
    "gst invoice",
    "bill",
    "bill of supply",
    "receipt",
    "cash receipt",
    "payment receipt",
    "cash memo",
    "estimate",
    "original for recipient",
    "duplicate",
    "customer copy",
}


def normalize_label(text: str) -> str:
    """Lowercase, trim punctuation, collapse spaces: 'Invoice No. :' -> 'invoice no'."""
    text = text.lower().replace("\xa0", " ")
    text = re.sub(r"[.:]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" -#()[]*")


@dataclass(frozen=True)
class LabelMatch:
    field: str
    label: str
    priority: int  # lower is stronger, the position in the field's list
    rest: str  # text after the label, e.g. the value in "Date: 14/08/2026"


def _boundary_after(text: str, label: str) -> bool:
    return len(text) == len(label) or not text[len(label)].isalnum()


def match_label(raw: str, fields: dict[str, list[str]] = FIELD_LABELS) -> LabelMatch | None:
    """The label a piece of text starts with. The longest matching label wins, so
    'total gst' is tax, not total."""
    lowered = raw.lower().replace("\xa0", " ").strip()
    normalized = normalize_label(raw)
    best: LabelMatch | None = None
    for field, labels in fields.items():
        for priority, label in enumerate(labels):
            if not normalized.startswith(label) or not _boundary_after(normalized, label):
                continue
            if best is not None and len(label) <= len(best.label):
                continue
            # Find the value after the label in the original text.
            words = label.split()
            pattern = r"\W*".join(re.escape(word) for word in words)
            found = re.match(rf"\W*{pattern}\b", lowered)
            rest = raw[found.end() :] if found else ""
            best = LabelMatch(field, label, priority, rest.strip(" :.-#\t|"))
    return best


def is_document_title(text: str) -> bool:
    return normalize_label(text) in DOCUMENT_TITLES
