"""The one output shape every extractor returns (hard rule 3).

Money is Decimal, never float, and always rupees. A field that could not be read is
None; an extractor never guesses.
"""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class LineItemSchema(BaseModel):
    model_config = ConfigDict(frozen=True)

    description: str
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    amount: Decimal


class ReceiptSchema(BaseModel):
    model_config = ConfigDict(frozen=True)

    vendor: str | None = None
    receipt_number: str | None = None
    receipt_date: date | None = None
    subtotal: Decimal | None = None
    tax: Decimal | None = None
    total: Decimal | None = None
    line_items: list[LineItemSchema] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    # Where in the file this receipt came from, e.g. "sheet: March" or "pages 1-2".
    source: str

    def missing_required(self) -> list[str]:
        """Names of the required fields that are empty (D-013 item 1)."""
        required = {"vendor": self.vendor, "receipt_date": self.receipt_date, "total": self.total}
        return [name for name, value in required.items() if value in (None, "")]
