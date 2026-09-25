"""Request and response bodies. The frontend's types are generated from these."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

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
