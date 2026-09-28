"""Request and response bodies. The frontend's types are generated from these."""

import unicodedata
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from parchi.db.enums import (
    AiProvider,
    FileKind,
    FileStatus,
    FlagSeverity,
    FlagType,
    RunParser,
    UserRole,
)
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
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_from_id: int | None = None
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


class AiExtractIn(BaseModel):
    """Approval to send one file to an AI provider (hard rule 1)."""

    provider: AiProvider
    approved: Literal[True] = Field(
        description="Must be true: the person confirmed the file will be sent to the provider"
    )


class AiBatchIn(AiExtractIn):
    """Approval for several files at once (D-036)."""

    files: list[str] = Field(min_length=1, max_length=50, description="Ids or reference numbers")


class AiRunOut(BaseModel):
    file_id: int
    ref_no: str
    run_id: int


class AiRunsOut(BaseModel):
    runs: list[AiRunOut]


class AiProviderInfo(BaseModel):
    provider: AiProvider
    label: str
    model: str
    configured: bool


class AiUsage(BaseModel):
    enabled: bool
    daily_cap: int
    used_today: int
    remaining: int
    providers: list[AiProviderInfo]


# --- Query (D-037 to D-039) ------------------------------------------------------------

QUERY_PAGE_SIZE = 50


class ReceiptQuery(BaseModel):
    """Filters for the Query page. With neither date, the financial year to date (D-028)."""

    model_config = ConfigDict(extra="forbid")

    date_from: date | None = None
    date_to: date | None = None
    vendor: str | None = Field(default=None, max_length=255, description="A normalized name")
    category_id: int | None = None
    min_total: Money | None = Field(default=None, ge=0)
    max_total: Money | None = Field(default=None, ge=0)
    sort: Literal["date", "amount"] = Field(
        default="date", description="date: oldest first; amount: largest first"
    )
    limit: int | None = Field(
        default=None, ge=1, le=500, description="Only the first N, e.g. top 5"
    )
    page: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _ranges(self) -> "ReceiptQuery":
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("From cannot be later than To.")
        if (
            self.min_total is not None
            and self.max_total is not None
            and self.min_total > self.max_total
        ):
            raise ValueError("The minimum amount cannot be more than the maximum.")
        return self


class ReceiptRow(BaseModel):
    ref_no: str
    file_ref_no: str
    receipt_date: date
    vendor: str
    receipt_number: str | None
    category: str | None
    subtotal: Decimal | None
    tax: Decimal | None
    total: Decimal


class ReceiptPage(BaseModel):
    items: list[ReceiptRow]
    count: int = Field(description="Every matching receipt, not just this page")
    sum_total: Decimal
    average_total: Decimal | None
    page: int
    page_size: int
    date_from: date | None
    date_to: date | None
    waiting_for_review: int = Field(description="Files not counted until a person reviews them")


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=300)


class Understood(BaseModel):
    label: str
    value: str


class AskOut(BaseModel):
    question: str
    understood_as: list[Understood]
    ignored: list[str] = Field(description="Words the reader did not understand")
    filters: ReceiptQuery
    sql: str = Field(description="The query that ran, on read-only access")
    result: ReceiptPage


# --- Login and users (D-043 to D-045) ----------------------------------------------------

PASSWORD_MIN, PASSWORD_MAX = 10, 128
Password = Annotated[str, Field(min_length=PASSWORD_MIN, max_length=PASSWORD_MAX)]
Username = Annotated[str, Field(min_length=3, max_length=50, pattern=r"^[A-Za-z0-9._-]{3,50}$")]
DisplayName = Annotated[str, Field(min_length=1, max_length=100)]


def _tidy_name(value: str) -> str:
    value = " ".join(value.split())
    if not value:
        raise ValueError("The name is required.")
    return value


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=PASSWORD_MAX)


class MeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: str
    role: UserRole
    must_change_password: bool


class SignupIn(BaseModel):
    """A new account made by the person themselves. The role is always Viewer (D-046)."""

    model_config = ConfigDict(extra="forbid")

    username: Username
    display_name: DisplayName
    password: Password

    @field_validator("username")
    @classmethod
    def _lower(cls, value: str) -> str:
        return value.lower()

    @field_validator("display_name")
    @classmethod
    def _name(cls, value: str) -> str:
        return _tidy_name(value)


class AuthOptions(BaseModel):
    signup: bool = Field(description="Whether people can create their own accounts")


class PasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=PASSWORD_MAX)
    new_password: Password


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: str
    role: UserRole
    active: bool
    must_change_password: bool
    last_login_at: datetime | None
    created_at: datetime


class UserCreateIn(BaseModel):
    username: Username
    display_name: DisplayName
    role: UserRole
    temporary_password: Password

    @field_validator("username")
    @classmethod
    def _lower(cls, value: str) -> str:
        return value.lower()

    @field_validator("display_name")
    @classmethod
    def _name(cls, value: str) -> str:
        return _tidy_name(value)


class UserUpdateIn(BaseModel):
    """Only the fields sent are changed."""

    display_name: DisplayName | None = None
    role: UserRole | None = None
    active: bool | None = None

    @field_validator("display_name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        return None if value is None else _tidy_name(value)


class PasswordResetIn(BaseModel):
    temporary_password: Password
