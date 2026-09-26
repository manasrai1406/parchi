"""User-managed categories (D-026).

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-26

Moves categories from a fixed list (a CHECK constraint on text columns) to a
`categories` table seeded with the eight built-in ones. Existing values are carried
over. Downgrading maps custom categories back to "other", the only text they can have.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BUILTIN = ("Fuel", "Travel", "Food", "Office", "Utilities", "Maintenance", "Services", "Other")
OLD_VALUES = ", ".join(f"'{name.lower()}'" for name in BUILTIN)


def upgrade() -> None:
    op.create_table(
        "categories",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("builtin", sa.Boolean, server_default=sa.false(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_categories")),
        sa.CheckConstraint(
            "name <> '' AND name = btrim(name) AND name !~ '[[:cntrl:]]'",
            name=op.f("ck_categories_name_clean"),
        ),
    )
    op.create_index(
        op.f("uq_categories_lower_name"), "categories", [sa.text("lower(name)")], unique=True
    )
    op.execute(
        "CREATE TRIGGER trg_categories_set_updated_at BEFORE UPDATE ON categories "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )
    categories = sa.table("categories", sa.column("name"), sa.column("builtin"))
    op.bulk_insert(categories, [{"name": name, "builtin": True} for name in BUILTIN])

    # Vendors: default_category (text) -> default_category_id.
    op.add_column("vendors", sa.Column("default_category_id", sa.BigInteger, nullable=True))
    op.execute(
        "UPDATE vendors v SET default_category_id = c.id FROM categories c"
        " WHERE lower(c.name) = v.default_category"
    )
    op.drop_constraint(op.f("ck_vendors_default_category"), "vendors", type_="check")
    op.drop_column("vendors", "default_category")
    op.create_foreign_key(
        op.f("fk_vendors_default_category_id_categories"),
        "vendors",
        "categories",
        ["default_category_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(op.f("ix_vendors_default_category_id"), "vendors", ["default_category_id"])

    # Receipts: category_auto / category_override (text) -> *_id; category -> category_id.
    op.add_column("receipts", sa.Column("category_auto_id", sa.BigInteger, nullable=True))
    op.add_column("receipts", sa.Column("category_override_id", sa.BigInteger, nullable=True))
    for old, new in (
        ("category_auto", "category_auto_id"),
        ("category_override", "category_override_id"),
    ):
        op.execute(
            f"UPDATE receipts r SET {new} = c.id FROM categories c WHERE lower(c.name) = r.{old}"
        )
    op.drop_index(op.f("ix_receipts_category"), table_name="receipts")
    op.drop_column("receipts", "category")
    for old in ("category_auto", "category_override"):
        op.drop_constraint(op.f(f"ck_receipts_{old}"), "receipts", type_="check")
        op.drop_column("receipts", old)
    for column in ("category_auto_id", "category_override_id"):
        op.create_foreign_key(
            op.f(f"fk_receipts_{column}_categories"),
            "receipts",
            "categories",
            [column],
            ["id"],
            ondelete="RESTRICT",
        )
        op.create_index(op.f(f"ix_receipts_{column}"), "receipts", [column])
    op.add_column(
        "receipts",
        sa.Column(
            "category_id",
            sa.BigInteger,
            sa.Computed("COALESCE(category_override_id, category_auto_id)", persisted=True),
            nullable=True,
        ),
    )
    op.create_index(op.f("ix_receipts_category_id"), "receipts", ["category_id"])


def downgrade() -> None:
    # Receipts back to text columns.
    op.drop_index(op.f("ix_receipts_category_id"), table_name="receipts")
    op.drop_column("receipts", "category_id")
    for old in ("category_auto", "category_override"):
        op.add_column("receipts", sa.Column(old, sa.String(11), nullable=True))
        op.execute(
            f"UPDATE receipts r SET {old} = CASE WHEN c.builtin THEN lower(c.name) ELSE 'other' END"
            f" FROM categories c WHERE c.id = r.{old}_id"
        )
        op.create_check_constraint(
            op.f(f"ck_receipts_{old}"), "receipts", f"{old} IN ({OLD_VALUES})"
        )
        op.drop_index(op.f(f"ix_receipts_{old}_id"), table_name="receipts")
        op.drop_constraint(op.f(f"fk_receipts_{old}_id_categories"), "receipts", type_="foreignkey")
        op.drop_column("receipts", f"{old}_id")
    op.add_column(
        "receipts",
        sa.Column(
            "category",
            sa.String(20),
            sa.Computed("COALESCE(category_override, category_auto)", persisted=True),
            nullable=True,
        ),
    )
    op.create_index(op.f("ix_receipts_category"), "receipts", ["category"])

    # Vendors back to a text column.
    op.add_column("vendors", sa.Column("default_category", sa.String(11), nullable=True))
    op.execute(
        "UPDATE vendors v SET default_category = CASE WHEN c.builtin THEN lower(c.name)"
        " ELSE 'other' END FROM categories c WHERE c.id = v.default_category_id"
    )
    op.create_check_constraint(
        op.f("ck_vendors_default_category"), "vendors", f"default_category IN ({OLD_VALUES})"
    )
    op.drop_index(op.f("ix_vendors_default_category_id"), table_name="vendors")
    op.drop_constraint(
        op.f("fk_vendors_default_category_id_categories"), "vendors", type_="foreignkey"
    )
    op.drop_column("vendors", "default_category_id")

    op.drop_table("categories")
