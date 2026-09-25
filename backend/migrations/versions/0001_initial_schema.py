"""Initial schema: batches, vendors, files, extraction runs, receipts, line items, flags.

Revision ID: 0001
Revises:
Create Date: 2026-09-26

Enum values are copied here on purpose: a migration is a snapshot and must not change
when parchi.db.enums changes later.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FILE_STATUSES = (
    "pending",
    "processing",
    "parsed",
    "needs_review",
    "ai_processing",
    "flagged",
    "resolved",
    "rejected",
    "failed",
)
FILE_KINDS = ("excel", "csv", "pdf_text", "pdf_scan", "image")
RUN_PARSERS = ("excel", "csv", "pdf_text", "pdf_scan", "image", "ai", "manual")
LIBRARY_PARSERS = ("excel", "csv", "pdf_text", "pdf_scan", "image")
AI_PROVIDERS = ("anthropic", "openai")
FLAG_TYPES = (
    "unreadable",
    "validation_failed",
    "parser_conflict",
    "duplicate_receipt",
    "arithmetic_mismatch",
)
FLAG_SEVERITIES = ("info", "warning", "error")
CATEGORIES = (
    "fuel",
    "travel",
    "food",
    "office",
    "utilities",
    "maintenance",
    "services",
    "other",
)

TABLES = (
    "upload_batches",
    "vendors",
    "files",
    "extraction_runs",
    "receipts",
    "line_items",
    "flags",
)


def _sql_list(values: Sequence[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _enum_check(table: str, column: str, values: Sequence[str]) -> sa.CheckConstraint:
    return sa.CheckConstraint(
        f"{column} IN ({_sql_list(values)})", name=op.f(f"ck_{table}_{column}")
    )


def _enum_column(column: str, values: Sequence[str], **kwargs: object) -> sa.Column:
    return sa.Column(column, sa.String(max(len(value) for value in values)), **kwargs)


def _id() -> sa.Column:
    return sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    op.execute(sa.schema.CreateSequence(sa.Sequence("file_ref_seq")))

    op.execute(
        """
        CREATE FUNCTION set_updated_at() RETURNS trigger AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )

    op.create_table(
        "upload_batches",
        _id(),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_upload_batches")),
    )

    op.create_table(
        "vendors",
        _id(),
        sa.Column("raw_name", sa.String(255), nullable=False),
        sa.Column("normalized_name", sa.String(255), nullable=False),
        _enum_column("default_category", CATEGORIES, nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vendors")),
        sa.UniqueConstraint("raw_name", name=op.f("uq_vendors_raw_name")),
        sa.CheckConstraint("raw_name <> ''", name=op.f("ck_vendors_raw_name_not_empty")),
        sa.CheckConstraint(
            "normalized_name <> ''", name=op.f("ck_vendors_normalized_name_not_empty")
        ),
        _enum_check("vendors", "default_category", CATEGORIES),
    )
    op.create_index(op.f("ix_vendors_normalized_name"), "vendors", ["normalized_name"])

    op.create_table(
        "files",
        _id(),
        sa.Column("ref_no", sa.String(24), nullable=False),
        sa.Column("batch_id", sa.BigInteger, nullable=False),
        sa.Column("original_name", sa.String(255), nullable=False),
        sa.Column("sha256", sa.CHAR(64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("storage_path", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(127), nullable=True),
        _enum_column("kind", FILE_KINDS, nullable=True),
        _enum_column("status", FILE_STATUSES, nullable=False, server_default="pending"),
        sa.Column(
            "status_changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("attempts", sa.SmallInteger, server_default="0", nullable=False),
        sa.Column("duplicate_of_id", sa.BigInteger, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_files")),
        sa.UniqueConstraint("ref_no", name=op.f("uq_files_ref_no")),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["upload_batches.id"],
            name=op.f("fk_files_batch_id_upload_batches"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["duplicate_of_id"],
            ["files.id"],
            name=op.f("fk_files_duplicate_of_id_files"),
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "ref_no ~ '^REF-[0-9]{4}-[0-9]{6,}$'", name=op.f("ck_files_ref_no_format")
        ),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_files_sha256_format")),
        sa.CheckConstraint("size_bytes >= 0", name=op.f("ck_files_size_bytes_non_negative")),
        sa.CheckConstraint("attempts >= 0", name=op.f("ck_files_attempts_non_negative")),
        sa.CheckConstraint(
            "original_name <> '' "
            "AND strpos(original_name, '/') = 0 "
            "AND strpos(original_name, chr(92)) = 0 "
            "AND original_name !~ '[[:cntrl:]]'",
            name=op.f("ck_files_original_name_safe"),
        ),
        sa.CheckConstraint(
            "storage_path <> '' "
            "AND left(storage_path, 1) NOT IN ('/', chr(92)) "
            "AND strpos(storage_path, '..') = 0",
            name=op.f("ck_files_storage_path_relative"),
        ),
        sa.CheckConstraint("duplicate_of_id <> id", name=op.f("ck_files_not_duplicate_of_self")),
        _enum_check("files", "kind", FILE_KINDS),
        _enum_check("files", "status", FILE_STATUSES),
    )
    op.create_index(op.f("ix_files_batch_id"), "files", ["batch_id"])
    op.create_index(op.f("ix_files_sha256"), "files", ["sha256"])
    op.create_index(op.f("ix_files_duplicate_of_id"), "files", ["duplicate_of_id"])
    op.create_index(
        op.f("ix_files_status_status_changed_at"), "files", ["status", "status_changed_at"]
    )

    op.create_table(
        "extraction_runs",
        _id(),
        sa.Column("file_id", sa.BigInteger, nullable=False),
        _enum_column("parser", RUN_PARSERS, nullable=False),
        _enum_column("provider", AI_PROVIDERS, nullable=True),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("result_json", postgresql.JSONB, nullable=True),
        sa.Column("confidence", sa.REAL, nullable=True),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("ai_approved_by", sa.String(100), nullable=True),
        sa.Column("ai_approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted", sa.Boolean, server_default=sa.false(), nullable=False),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_extraction_runs")),
        sa.UniqueConstraint("id", "file_id", name=op.f("uq_extraction_runs_id_file_id")),
        sa.ForeignKeyConstraint(
            ["file_id"],
            ["files.id"],
            name=op.f("fk_extraction_runs_file_id_files"),
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "parser <> 'ai' OR (provider IS NOT NULL "
            "AND ai_approved_by IS NOT NULL AND ai_approved_at IS NOT NULL)",
            name=op.f("ck_extraction_runs_ai_requires_approval"),
        ),
        sa.CheckConstraint(
            "parser = 'ai' OR (provider IS NULL AND model IS NULL "
            "AND ai_approved_by IS NULL AND ai_approved_at IS NULL)",
            name=op.f("ck_extraction_runs_non_ai_has_no_ai_fields"),
        ),
        sa.CheckConstraint(
            "NOT accepted OR (error IS NULL AND result_json IS NOT NULL "
            "AND finished_at IS NOT NULL)",
            name=op.f("ck_extraction_runs_accepted_run_succeeded"),
        ),
        sa.CheckConstraint(
            "confidence BETWEEN 0 AND 1", name=op.f("ck_extraction_runs_confidence_range")
        ),
        sa.CheckConstraint(
            "duration_ms >= 0", name=op.f("ck_extraction_runs_duration_non_negative")
        ),
        _enum_check("extraction_runs", "parser", RUN_PARSERS),
        _enum_check("extraction_runs", "provider", AI_PROVIDERS),
    )
    op.create_index(op.f("ix_extraction_runs_file_id"), "extraction_runs", ["file_id"])
    op.create_index(
        op.f("uq_extraction_runs_one_accepted_per_file"),
        "extraction_runs",
        ["file_id"],
        unique=True,
        postgresql_where=sa.text("accepted"),
    )
    op.create_index(
        op.f("uq_extraction_runs_one_library_run_per_file"),
        "extraction_runs",
        ["file_id"],
        unique=True,
        postgresql_where=sa.text(f"parser IN ({_sql_list(LIBRARY_PARSERS)})"),
    )
    op.create_index(
        op.f("ix_extraction_runs_ai_approved_at"),
        "extraction_runs",
        ["ai_approved_at"],
        postgresql_where=sa.text("parser = 'ai'"),
    )

    op.create_table(
        "receipts",
        _id(),
        sa.Column("file_id", sa.BigInteger, nullable=False),
        sa.Column("run_id", sa.BigInteger, nullable=False),
        sa.Column("seq", sa.SmallInteger, nullable=False),
        sa.Column("ref_no", sa.String(32), nullable=False),
        sa.Column("vendor_id", sa.BigInteger, nullable=False),
        sa.Column("receipt_number", sa.String(64), nullable=True),
        sa.Column("receipt_date", sa.Date, nullable=False),
        sa.Column("subtotal", sa.Numeric(12, 2), nullable=True),
        sa.Column("tax", sa.Numeric(12, 2), nullable=True),
        sa.Column("total", sa.Numeric(12, 2), nullable=False),
        _enum_column("category_auto", CATEGORIES, nullable=True),
        _enum_column("category_override", CATEGORIES, nullable=True),
        sa.Column(
            "category",
            sa.String(20),
            sa.Computed("COALESCE(category_override, category_auto)", persisted=True),
            nullable=True,
        ),
        sa.Column("confidence", sa.REAL, nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_receipts")),
        sa.UniqueConstraint("ref_no", name=op.f("uq_receipts_ref_no")),
        sa.UniqueConstraint("file_id", "seq", name=op.f("uq_receipts_file_id_seq")),
        sa.ForeignKeyConstraint(
            ["file_id"],
            ["files.id"],
            name=op.f("fk_receipts_file_id_files"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "file_id"],
            ["extraction_runs.id", "extraction_runs.file_id"],
            name=op.f("fk_receipts_run_id_file_id_extraction_runs"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["vendor_id"],
            ["vendors.id"],
            name=op.f("fk_receipts_vendor_id_vendors"),
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("seq >= 1", name=op.f("ck_receipts_seq_positive")),
        sa.CheckConstraint(
            "ref_no ~ '^REF-[0-9]{4}-[0-9]{6,}-[0-9]{2,}$'", name=op.f("ck_receipts_ref_no_format")
        ),
        sa.CheckConstraint(
            "ref_no = regexp_replace(ref_no, '-[0-9]+$', '') || '-' "
            "|| lpad(seq::text, greatest(2, length(seq::text)), '0')",
            name=op.f("ck_receipts_ref_no_matches_seq"),
        ),
        sa.CheckConstraint("confidence BETWEEN 0 AND 1", name=op.f("ck_receipts_confidence_range")),
        _enum_check("receipts", "category_auto", CATEGORIES),
        _enum_check("receipts", "category_override", CATEGORIES),
    )
    op.create_index(op.f("ix_receipts_run_id"), "receipts", ["run_id"])
    op.create_index(op.f("ix_receipts_vendor_id"), "receipts", ["vendor_id"])
    op.create_index(op.f("ix_receipts_receipt_date"), "receipts", ["receipt_date"])
    op.create_index(op.f("ix_receipts_category"), "receipts", ["category"])
    op.create_index(
        op.f("ix_receipts_vendor_id_receipt_number_total"),
        "receipts",
        ["vendor_id", "receipt_number", "total"],
    )

    op.create_table(
        "line_items",
        _id(),
        sa.Column("receipt_id", sa.BigInteger, nullable=False),
        sa.Column("position", sa.SmallInteger, nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("quantity", sa.Numeric(12, 3), nullable=True),
        sa.Column("unit_price", sa.Numeric(14, 4), nullable=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_line_items")),
        sa.UniqueConstraint(
            "receipt_id", "position", name=op.f("uq_line_items_receipt_id_position")
        ),
        sa.ForeignKeyConstraint(
            ["receipt_id"],
            ["receipts.id"],
            name=op.f("fk_line_items_receipt_id_receipts"),
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("position >= 1", name=op.f("ck_line_items_position_positive")),
    )

    op.create_table(
        "flags",
        _id(),
        sa.Column("file_id", sa.BigInteger, nullable=False),
        sa.Column("receipt_id", sa.BigInteger, nullable=True),
        _enum_column("type", FLAG_TYPES, nullable=False),
        _enum_column("severity", FLAG_SEVERITIES, nullable=False),
        sa.Column("detail", sa.Text, nullable=False),
        sa.Column("dedupe_key", sa.String(200), nullable=False),
        sa.Column("resolved", sa.Boolean, server_default=sa.false(), nullable=False),
        sa.Column("resolved_by", sa.String(100), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_flags")),
        sa.ForeignKeyConstraint(
            ["file_id"], ["files.id"], name=op.f("fk_flags_file_id_files"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["receipt_id"],
            ["receipts.id"],
            name=op.f("fk_flags_receipt_id_receipts"),
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "(resolved AND resolved_by IS NOT NULL AND resolved_at IS NOT NULL) "
            "OR (NOT resolved AND resolved_by IS NULL AND resolved_at IS NULL)",
            name=op.f("ck_flags_resolution_consistent"),
        ),
        sa.CheckConstraint("dedupe_key <> ''", name=op.f("ck_flags_dedupe_key_not_empty")),
        _enum_check("flags", "type", FLAG_TYPES),
        _enum_check("flags", "severity", FLAG_SEVERITIES),
    )
    op.create_index(op.f("ix_flags_file_id"), "flags", ["file_id"])
    op.create_index(op.f("ix_flags_receipt_id"), "flags", ["receipt_id"])
    op.create_index(
        op.f("uq_flags_open_type_dedupe_key"),
        "flags",
        ["type", "dedupe_key"],
        unique=True,
        postgresql_where=sa.text("NOT resolved"),
    )
    op.create_index(
        op.f("ix_flags_open_file_id"),
        "flags",
        ["file_id"],
        postgresql_where=sa.text("NOT resolved"),
    )

    for table in TABLES:
        op.execute(
            f"CREATE TRIGGER trg_{table}_set_updated_at BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
        )


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table)
    op.execute("DROP FUNCTION set_updated_at()")
    op.execute(sa.schema.DropSequence(sa.Sequence("file_ref_seq")))
