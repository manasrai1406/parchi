"""Allow Gemini as an AI provider (D-041).

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NAME = "ck_extraction_runs_provider"
# The allowed providers from now on; tests/unit/test_schema.py checks it against the code.
AI_PROVIDERS = ("anthropic", "openai", "gemini")


def _replace(values: Sequence[str]) -> None:
    listed = ", ".join(f"'{value}'" for value in values)
    op.drop_constraint(op.f(NAME), "extraction_runs", type_="check")
    op.create_check_constraint(op.f(NAME), "extraction_runs", f"provider IN ({listed})")


def upgrade() -> None:
    _replace(AI_PROVIDERS)


def downgrade() -> None:
    # Fails if any run used Gemini; delete those runs first.
    _replace(("anthropic", "openai"))
