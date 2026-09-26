"""The instructions and JSON schema sent with every AI request, and reading the answer.

The same schema goes to both providers (strict structured output), so the answer has
Parchi's receipt shape before our own normalizing and checks run on it.
"""

from typing import Any

from parchi.extraction.normalize import (
    clean_receipt_number,
    clean_vendor,
    parse_amount,
    parse_date,
    parse_quantity,
)
from parchi.schemas.receipt import LineItemSchema, ReceiptSchema

# Neither provider reports a confidence; AI results get this fixed value (D-035).
AI_CONFIDENCE = 0.9

SYSTEM_PROMPT = (
    "You read Indian receipts and invoices and return their fields as JSON. Amounts are in "
    "rupees (INR). Copy values exactly as printed; never invent or estimate one. If a value "
    "is not printed or cannot be read, return null for it."
)

INSTRUCTIONS = """Extract every receipt in this file. A file may hold several receipts \
(one per page or sheet); a receipt continued over several pages is one receipt.

For each receipt:
- vendor: the business that issued it, as printed (not the customer).
- receipt_number: the invoice, bill or receipt number, as printed.
- receipt_date: the invoice or bill date as YYYY-MM-DD. Dates are day-first in India: \
03/04/2026 is 3 April 2026. Prefer the invoice date over an order date.
- subtotal: the amount before tax (taxable value), if printed.
- tax: the total tax (add up CGST, SGST, IGST, UTGST and cess if printed separately). \
Never return a tax rate such as 18%; return the amount.
- total: the final amount payable (grand total).
- line_items: each item with its description, quantity, unit price and amount.

Write amounts as plain numbers with a dot for decimals and no currency or commas, \
e.g. "1180.00"."""

_TEXT_OR_NULL: dict[str, Any] = {"anyOf": [{"type": "string"}, {"type": "null"}]}

RECEIPTS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["receipts"],
    "properties": {
        "receipts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "vendor",
                    "receipt_number",
                    "receipt_date",
                    "subtotal",
                    "tax",
                    "total",
                    "line_items",
                ],
                "properties": {
                    "vendor": _TEXT_OR_NULL,
                    "receipt_number": _TEXT_OR_NULL,
                    "receipt_date": _TEXT_OR_NULL,
                    "subtotal": _TEXT_OR_NULL,
                    "tax": _TEXT_OR_NULL,
                    "total": _TEXT_OR_NULL,
                    "line_items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["description", "quantity", "unit_price", "amount"],
                            "properties": {
                                "description": {"type": "string"},
                                "quantity": _TEXT_OR_NULL,
                                "unit_price": _TEXT_OR_NULL,
                                "amount": _TEXT_OR_NULL,
                            },
                        },
                    },
                },
            },
        }
    },
}


def to_receipts(data: dict[str, Any], source: str) -> list[ReceiptSchema]:
    """The provider's JSON as normalized receipts. Values that don't parse become None,
    exactly as for a library reader, so the same checks decide what happens next."""
    receipts = []
    for raw in data.get("receipts") or []:
        items = []
        for item in raw.get("line_items") or []:
            amount = parse_amount(item.get("amount"))
            description = (item.get("description") or "").strip()
            if amount is None or not description:
                continue
            items.append(
                LineItemSchema(
                    description=description[:500],
                    quantity=parse_quantity(item.get("quantity")),
                    unit_price=parse_amount(item.get("unit_price")),
                    amount=amount,
                )
            )
        receipts.append(
            ReceiptSchema(
                vendor=clean_vendor(raw.get("vendor")),
                receipt_number=clean_receipt_number(raw.get("receipt_number")),
                receipt_date=parse_date(raw.get("receipt_date")),
                subtotal=parse_amount(raw.get("subtotal")),
                tax=parse_amount(raw.get("tax")),
                total=parse_amount(raw.get("total")),
                line_items=items,
                confidence=AI_CONFIDENCE,
                source=source,
            )
        )
    return receipts
