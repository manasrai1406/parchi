"""Labels learned from people's corrections, and the text each reader saw (D-048).

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEARNED_FIELDS = ("subtotal", "tax", "total")


def upgrade() -> None:
    op.add_column("extraction_runs", sa.Column("text", sa.Text, nullable=True))

    fields = ", ".join(f"'{field}'" for field in LEARNED_FIELDS)
    op.create_table(
        "vendor_labels",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("vendor_key", sa.String(255), nullable=False),
        sa.Column("field", sa.String(10), nullable=False),
        sa.Column("label", sa.String(60), nullable=False),
        sa.Column("taught_by", sa.String(50), nullable=False),
        sa.Column("taught_from_run_id", sa.BigInteger, nullable=True),
        sa.Column("times_used", sa.Integer, server_default="0", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vendor_labels")),
        sa.UniqueConstraint(
            "vendor_key", "field", "label", name=op.f("uq_vendor_labels_vendor_key_field_label")
        ),
        sa.ForeignKeyConstraint(
            ["taught_from_run_id"],
            ["extraction_runs.id"],
            name=op.f("fk_vendor_labels_taught_from_run_id_extraction_runs"),
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(f"field IN ({fields})", name=op.f("ck_vendor_labels_field_known")),
        sa.CheckConstraint(
            "label <> '' AND label = lower(label)", name=op.f("ck_vendor_labels_label_clean")
        ),
        sa.CheckConstraint(
            "vendor_key <> '' AND vendor_key = lower(vendor_key)",
            name=op.f("ck_vendor_labels_vendor_key_clean"),
        ),
        sa.CheckConstraint("times_used >= 0", name=op.f("ck_vendor_labels_times_used_positive")),
    )
    op.create_index("ix_vendor_labels_field_label", "vendor_labels", ["field", "label"])
    op.create_index(
        op.f("ix_vendor_labels_taught_from_run_id"), "vendor_labels", ["taught_from_run_id"]
    )
    op.execute(
        "CREATE TRIGGER trg_vendor_labels_set_updated_at BEFORE UPDATE ON vendor_labels "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )


def downgrade() -> None:
    op.drop_table("vendor_labels")
    op.drop_column("extraction_runs", "text")
