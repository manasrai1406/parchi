"""The receipt view and the read-only role the Query page uses (D-038).

The role belongs to the whole PostgreSQL server, not this database, so it is created only
if missing and left in place on downgrade.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

READER = "parchi_reader"


def upgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{READER}') THEN
                CREATE ROLE {READER} NOLOGIN;
            END IF;
        END
        $$
        """
    )
    # The app's own user switches to the role with SET ROLE, so it needs to be a member.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT pg_has_role(current_user, '{READER}', 'MEMBER') THEN
                EXECUTE format('GRANT {READER} TO %I', current_user);
            END IF;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE VIEW receipt_view AS
        SELECT
            r.id,
            r.ref_no,
            f.ref_no AS file_ref_no,
            f.status,
            r.receipt_date,
            v.normalized_name AS vendor,
            r.receipt_number,
            r.category_id,
            c.name AS category,
            r.subtotal,
            r.tax,
            r.total
        FROM receipts r
        JOIN files f ON f.id = r.file_id
        JOIN vendors v ON v.id = r.vendor_id
        LEFT JOIN categories c ON c.id = r.category_id
        """
    )
    op.execute("REVOKE ALL ON receipt_view FROM PUBLIC")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {READER}")
    op.execute(f"GRANT SELECT ON receipt_view TO {READER}")


def downgrade() -> None:
    op.execute("DROP VIEW receipt_view")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {READER}")
