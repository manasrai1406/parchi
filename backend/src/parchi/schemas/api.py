"""Request and response bodies. The frontend's types are generated from these."""

import unicodedata
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from parchi.db.enums import AiProvider, FileKind, FileStatus, FlagSeverity, FlagType, RunParser
from parchi.schemas.receipt import ReceiptSchema


class FileRef(BaseModel):
    """Enough to name and link to a file."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    ref_no: str
    original_name: str


class FileSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True, validate_by_name=True, validate_by_alias=True)

    id: int
    ref_no: str
    original_name: str
    size_bytes: int
    kind: FileKind | None
    status: FileStatus
    error: str | None
    uploaded_at: datetime = Field(validation_alias="created_at")
    duplicate_of: FileRef | None
    open_flags: int = Field(description="Unresolved problems a person should look at")


class BatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


class BatchDetail(BatchOut):
    files: list[FileSummary]


class RegisteredResult(BaseModel):
    result: Literal["registered"] = "registered"
    file: FileSummary


class DuplicateResult(BaseModel):
    """Nothing was saved. Upload again with confirm_duplicate=true to keep a copy (D-015)."""

    result: Literal["duplicate"] = "duplicate"
    duplicate_of: FileRef


UploadResult = Annotated[RegisteredResult | DuplicateResult, Field(discriminator="result")]


class FilePage(BaseModel):
    items: list[FileSummary]
    total: int
    page: int
    page_size: int


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    builtin: bool
    in_use: int = Field(description="Receipts and vendors using this category")


class CategoryIn(BaseModel):
    """A category name: spacing tidied, 1 to 50 characters, no control characters."""

    name: str

    @field_validator("name")
    @classmethod
    def _clean(cls, value: str) -> str:
        name = " ".join(value.split())
        if not name:
            raise ValueError("A category needs a name.")
        if len(name) > 50:
            raise ValueError("Category names can be at most 50 characters.")
        if any(unicodedata.category(char).startswith("C") for char in name):
            raise ValueError("Category names cannot contain control characters.")
        return name


class FileCounts(BaseModel):
    """For the summary cards, the status chips and the sidebar badges."""

    total: int
    by_status: dict[FileStatus, int]
    with_warnings: int = Field(description="Parsed files that have open warning flags")
    needs_attention: int = Field(
        description="Needs review + flagged + parsed with warnings: the Review queue"
    )


Money = Annotated[Decimal, Field(max_digits=12, decimal_places=2)]


class LineItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    position: int
    description: str
    quantity: Decimal | None
    unit_price: Decimal | None
    amount: Decimal


class ReceiptOut(BaseModel):
    id: int
    ref_no: str
    seq: int
    vendor: str
    receipt_number: str | None
    receipt_date: date
    subtotal: Decimal | None
    tax: Decimal | None
    total: Decimal
    category_id: int | None
    category_auto_id: int | None
    category_override_id: int | None
    confidence: float | None
    line_items: list[LineItemOut]


class FlagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: FlagType
    severity: FlagSeverity
    detail: str
    receipt_id: int | None
    resolved: bool
    resolved_by: str | None
    resolved_at: datetime | None
    created_at: datetime


class RunOut(BaseModel):
    """One extraction attempt. `result` is what that reader found, accepted or not."""

    id: int
    parser: RunParser
    provider: AiProvider | None
    model: str | None
    confidence: float | None
    duration_ms: int | None
    accepted: bool
    error: str | None
    ai_approved_by: str | None
    ai_approved_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    result: list[ReceiptSchema] | None


class FileDetail(FileSummary):
    """Everything the Review page shows for one file."""

    receipts: list[ReceiptOut]
    flags: list[FlagOut]
    runs: list[RunOut]


class LineItemIn(BaseModel):
    description: str = Field(min_length=1, max_length=500)
    quantity: Annotated[Decimal, Field(max_digits=12, decimal_places=3)] | None = None
    unit_price: Annotated[Decimal, Field(max_digits=14, decimal_places=4)] | None = None
    amount: Money


class ReceiptIn(BaseModel):
    """A receipt as a person entered or corrected it on the Review page."""

    vendor: str = Field(min_length=1, max_length=255)
    receipt_number: str | None = Field(default=None, max_length=64)
    receipt_date: date
    subtotal: Money | None = None
    tax: Money | None = None
    total: Money
    category_id: int | None = Field(default=None, description="The person's category choice")
    line_items: list[LineItemIn] = Field(default_factory=list, max_length=500)

    @field_validator("vendor")
    @classmethod
    def _vendor(cls, value: str) -> str:
        text = " ".join(value.split())
        if not text:
            raise ValueError("The vendor is required.")
        return text

    @field_validator("receipt_number")
    @classmethod
    def _number(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return " ".join(value.split()) or None


class ManualEdit(BaseModel):
    receipts: list[ReceiptIn] = Field(min_length=1, max_length=200)


class RejectIn(BaseModel):
    reason: str = Field(min_length=1, max_length=300, description="e.g. Not a receipt")
