"""Request and response bodies. The frontend's types are generated from these."""

import unicodedata
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from parchi.db.enums import FileKind, FileStatus


class FileRef(BaseModel):
    """Enough to name and link to a file."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    ref_no: str
    original_name: str


class FileSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ref_no: str
    original_name: str
    size_bytes: int
    kind: FileKind | None
    status: FileStatus
    error: str | None
    uploaded_at: datetime = Field(validation_alias="created_at")
    duplicate_of: FileRef | None


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
