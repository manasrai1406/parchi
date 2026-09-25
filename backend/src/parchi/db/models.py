"""Database tables. See docs/PLAN.md (Data model) and docs/decisions.md."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from parchi.db.base import Base, IdMixin, Money, TimestampMixin, enum_type
from parchi.db.enums import (
    LIBRARY_PARSERS,
    AiProvider,
    Category,
    FileKind,
    FileStatus,
    FlagSeverity,
    FlagType,
    RunParser,
)

# One global counter for file reference numbers. It never resets (D-013).
file_ref_seq = sa.Sequence("file_ref_seq", metadata=Base.metadata)

FILE_REF_PATTERN = r"^REF-[0-9]{4}-[0-9]{6,}$"
RECEIPT_REF_PATTERN = r"^REF-[0-9]{4}-[0-9]{6,}-[0-9]{2,}$"

_library_parsers_sql = ", ".join(f"'{parser.value}'" for parser in LIBRARY_PARSERS)


class UploadBatch(IdMixin, TimestampMixin, Base):
    __tablename__ = "upload_batches"

    files: Mapped[list["File"]] = relationship(back_populates="batch", lazy="raise")


class Vendor(IdMixin, TimestampMixin, Base):
    """Maps a vendor name as printed to one normalized name (D-002)."""

    __tablename__ = "vendors"
    __table_args__ = (
        sa.CheckConstraint("raw_name <> ''", name="raw_name_not_empty"),
        sa.CheckConstraint("normalized_name <> ''", name="normalized_name_not_empty"),
    )

    raw_name: Mapped[str] = mapped_column(sa.String(255), unique=True)
    normalized_name: Mapped[str] = mapped_column(sa.String(255), index=True)
    default_category: Mapped[Category | None] = mapped_column(
        enum_type(Category, "default_category")
    )


class File(IdMixin, TimestampMixin, Base):
    __tablename__ = "files"
    __table_args__ = (
        sa.CheckConstraint(f"ref_no ~ '{FILE_REF_PATTERN}'", name="ref_no_format"),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256_format"),
        sa.CheckConstraint("size_bytes >= 0", name="size_bytes_non_negative"),
        sa.CheckConstraint("attempts >= 0", name="attempts_non_negative"),
        sa.CheckConstraint(
            "original_name <> '' "
            "AND strpos(original_name, '/') = 0 "
            "AND strpos(original_name, chr(92)) = 0 "
            "AND original_name !~ '[[:cntrl:]]'",
            name="original_name_safe",
        ),
        sa.CheckConstraint(
            "storage_path <> '' "
            "AND left(storage_path, 1) NOT IN ('/', chr(92)) "
            "AND strpos(storage_path, '..') = 0",
            name="storage_path_relative",
        ),
        sa.CheckConstraint("duplicate_of_id <> id", name="not_duplicate_of_self"),
        sa.Index("ix_files_status_status_changed_at", "status", "status_changed_at"),
    )

    ref_no: Mapped[str] = mapped_column(sa.String(24), unique=True)
    batch_id: Mapped[int] = mapped_column(
        sa.ForeignKey("upload_batches.id", ondelete="RESTRICT"), index=True
    )
    original_name: Mapped[str] = mapped_column(sa.String(255))
    # Not unique: a person may confirm saving an identical file (D-006).
    sha256: Mapped[str] = mapped_column(sa.CHAR(64), index=True)
    size_bytes: Mapped[int] = mapped_column(sa.BigInteger)
    storage_path: Mapped[str] = mapped_column(sa.String(255))
    mime_type: Mapped[str | None] = mapped_column(sa.String(127))
    kind: Mapped[FileKind | None] = mapped_column(enum_type(FileKind, "kind"))
    status: Mapped[FileStatus] = mapped_column(
        enum_type(FileStatus, "status"), server_default=FileStatus.PENDING.value
    )
    status_changed_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    attempts: Mapped[int] = mapped_column(sa.SmallInteger, server_default="0")
    duplicate_of_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("files.id", ondelete="RESTRICT"), index=True
    )
    error: Mapped[str | None] = mapped_column(sa.Text)

    batch: Mapped[UploadBatch] = relationship(back_populates="files", lazy="raise")
    runs: Mapped[list["ExtractionRun"]] = relationship(back_populates="file", lazy="raise")
    receipts: Mapped[list["Receipt"]] = relationship(
        back_populates="file", lazy="raise", order_by="Receipt.seq"
    )
    flags: Mapped[list["Flag"]] = relationship(back_populates="file", lazy="raise")


class ExtractionRun(IdMixin, TimestampMixin, Base):
    """Every extraction attempt, kept so a re-run never overwrites an earlier result."""

    __tablename__ = "extraction_runs"
    __table_args__ = (
        # Backs up hard rule 1 in the database: an AI run always records its approval.
        sa.CheckConstraint(
            "parser <> 'ai' OR (provider IS NOT NULL "
            "AND ai_approved_by IS NOT NULL AND ai_approved_at IS NOT NULL)",
            name="ai_requires_approval",
        ),
        sa.CheckConstraint(
            "parser = 'ai' OR (provider IS NULL AND model IS NULL "
            "AND ai_approved_by IS NULL AND ai_approved_at IS NULL)",
            name="non_ai_has_no_ai_fields",
        ),
        sa.CheckConstraint(
            "NOT accepted OR (error IS NULL AND result_json IS NOT NULL "
            "AND finished_at IS NOT NULL)",
            name="accepted_run_succeeded",
        ),
        sa.CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_range"),
        sa.CheckConstraint("duration_ms >= 0", name="duration_non_negative"),
        # Target of the composite foreign key from receipts.
        sa.UniqueConstraint("id", "file_id"),
        # At most one accepted run per file (D-004).
        sa.Index(
            "uq_extraction_runs_one_accepted_per_file",
            "file_id",
            unique=True,
            postgresql_where=sa.text("accepted"),
        ),
        # One library run per file (PLAN.md), so a retried stage cannot add a second.
        sa.Index(
            "uq_extraction_runs_one_library_run_per_file",
            "file_id",
            unique=True,
            postgresql_where=sa.text(f"parser IN ({_library_parsers_sql})"),
        ),
        # Counting today's approved AI runs for the daily cap.
        sa.Index(
            "ix_extraction_runs_ai_approved_at",
            "ai_approved_at",
            postgresql_where=sa.text("parser = 'ai'"),
        ),
    )

    file_id: Mapped[int] = mapped_column(sa.ForeignKey("files.id", ondelete="RESTRICT"), index=True)
    parser: Mapped[RunParser] = mapped_column(enum_type(RunParser, "parser"))
    provider: Mapped[AiProvider | None] = mapped_column(enum_type(AiProvider, "provider"))
    model: Mapped[str | None] = mapped_column(sa.String(100))
    result_json: Mapped[Any | None] = mapped_column(JSONB)
    confidence: Mapped[float | None] = mapped_column(sa.REAL)
    duration_ms: Mapped[int | None] = mapped_column(sa.Integer)
    ai_approved_by: Mapped[str | None] = mapped_column(sa.String(100))
    ai_approved_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    accepted: Mapped[bool] = mapped_column(sa.Boolean, server_default=sa.false())
    error: Mapped[str | None] = mapped_column(sa.Text)
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    file: Mapped[File] = relationship(back_populates="runs", lazy="raise")


class Receipt(IdMixin, TimestampMixin, Base):
    """The accepted, normalized result. Only parsed and resolved files have receipts."""

    __tablename__ = "receipts"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["run_id", "file_id"],
            ["extraction_runs.id", "extraction_runs.file_id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("file_id", "seq"),
        sa.CheckConstraint("seq >= 1", name="seq_positive"),
        sa.CheckConstraint(f"ref_no ~ '{RECEIPT_REF_PATTERN}'", name="ref_no_format"),
        sa.CheckConstraint(
            "ref_no = regexp_replace(ref_no, '-[0-9]+$', '') || '-' "
            "|| lpad(seq::text, greatest(2, length(seq::text)), '0')",
            name="ref_no_matches_seq",
        ),
        sa.CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_range"),
        sa.Index(
            "ix_receipts_vendor_id_receipt_number_total", "vendor_id", "receipt_number", "total"
        ),
    )

    file_id: Mapped[int] = mapped_column(sa.ForeignKey("files.id", ondelete="RESTRICT"))
    run_id: Mapped[int] = mapped_column(sa.BigInteger, index=True)
    seq: Mapped[int] = mapped_column(sa.SmallInteger)
    ref_no: Mapped[str] = mapped_column(sa.String(32), unique=True)
    vendor_id: Mapped[int] = mapped_column(
        sa.ForeignKey("vendors.id", ondelete="RESTRICT"), index=True
    )
    receipt_number: Mapped[str | None] = mapped_column(sa.String(64))
    receipt_date: Mapped[date] = mapped_column(sa.Date, index=True)
    subtotal: Mapped[Decimal | None] = mapped_column(Money)
    tax: Mapped[Decimal | None] = mapped_column(Money)
    total: Mapped[Decimal] = mapped_column(Money)
    category_auto: Mapped[Category | None] = mapped_column(enum_type(Category, "category_auto"))
    category_override: Mapped[Category | None] = mapped_column(
        enum_type(Category, "category_override")
    )
    # The override wins over the automatic category (D-003, D-009).
    category: Mapped[str | None] = mapped_column(
        sa.String(20),
        sa.Computed("COALESCE(category_override, category_auto)", persisted=True),
        index=True,
    )
    confidence: Mapped[float | None] = mapped_column(sa.REAL)

    file: Mapped[File] = relationship(back_populates="receipts", lazy="raise")
    vendor: Mapped[Vendor] = relationship(lazy="raise")
    line_items: Mapped[list["LineItem"]] = relationship(
        back_populates="receipt",
        lazy="raise",
        order_by="LineItem.position",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class LineItem(IdMixin, TimestampMixin, Base):
    __tablename__ = "line_items"
    __table_args__ = (
        sa.UniqueConstraint("receipt_id", "position"),
        sa.CheckConstraint("position >= 1", name="position_positive"),
    )

    receipt_id: Mapped[int] = mapped_column(sa.ForeignKey("receipts.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(sa.SmallInteger)
    description: Mapped[str] = mapped_column(sa.Text)
    quantity: Mapped[Decimal | None] = mapped_column(sa.Numeric(12, 3))
    unit_price: Mapped[Decimal | None] = mapped_column(sa.Numeric(14, 4))
    amount: Mapped[Decimal] = mapped_column(Money)

    receipt: Mapped[Receipt] = relationship(back_populates="line_items", lazy="raise")


class Flag(IdMixin, TimestampMixin, Base):
    """A problem a person must look at."""

    __tablename__ = "flags"
    __table_args__ = (
        sa.CheckConstraint(
            "(resolved AND resolved_by IS NOT NULL AND resolved_at IS NOT NULL) "
            "OR (NOT resolved AND resolved_by IS NULL AND resolved_at IS NULL)",
            name="resolution_consistent",
        ),
        sa.CheckConstraint("dedupe_key <> ''", name="dedupe_key_not_empty"),
        # Re-running a check must not open the same flag twice.
        sa.Index(
            "uq_flags_open_type_dedupe_key",
            "type",
            "dedupe_key",
            unique=True,
            postgresql_where=sa.text("NOT resolved"),
        ),
        sa.Index("ix_flags_open_file_id", "file_id", postgresql_where=sa.text("NOT resolved")),
    )

    file_id: Mapped[int] = mapped_column(sa.ForeignKey("files.id", ondelete="RESTRICT"), index=True)
    # SET NULL keeps a flag's history when a file's receipts are replaced (D-013).
    receipt_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("receipts.id", ondelete="SET NULL"), index=True
    )
    type: Mapped[FlagType] = mapped_column(enum_type(FlagType, "type"))
    severity: Mapped[FlagSeverity] = mapped_column(enum_type(FlagSeverity, "severity"))
    detail: Mapped[str] = mapped_column(sa.Text)
    dedupe_key: Mapped[str] = mapped_column(sa.String(200))
    resolved: Mapped[bool] = mapped_column(sa.Boolean, server_default=sa.false())
    resolved_by: Mapped[str | None] = mapped_column(sa.String(100))
    resolved_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    file: Mapped[File] = relationship(back_populates="flags", lazy="raise")


ALL_TABLES = [
    table.name
    for table in (
        UploadBatch.__table__,
        Vendor.__table__,
        File.__table__,
        ExtractionRun.__table__,
        Receipt.__table__,
        LineItem.__table__,
        Flag.__table__,
    )
]
