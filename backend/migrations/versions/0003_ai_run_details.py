"""Token counts and cache links on AI extraction runs (D-036).

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("extraction_runs", sa.Column("input_tokens", sa.Integer, nullable=True))
    op.add_column("extraction_runs", sa.Column("output_tokens", sa.Integer, nullable=True))
    op.add_column("extraction_runs", sa.Column("cached_from_id", sa.BigInteger, nullable=True))
    op.create_foreign_key(
        op.f("fk_extraction_runs_cached_from_id_extraction_runs"),
        "extraction_runs",
        "extraction_runs",
        ["cached_from_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_extraction_runs_cached_from_id"), "extraction_runs", ["cached_from_id"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_extraction_runs_cached_from_id"), table_name="extraction_runs")
    op.drop_constraint(
        op.f("fk_extraction_runs_cached_from_id_extraction_runs"),
        "extraction_runs",
        type_="foreignkey",
    )
    op.drop_column("extraction_runs", "cached_from_id")
    op.drop_column("extraction_runs", "output_tokens")
    op.drop_column("extraction_runs", "input_tokens")
