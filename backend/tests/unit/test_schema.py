"""Checks on the table definitions that do not need a database."""

import importlib.util
from enum import StrEnum
from pathlib import Path

import pytest

from parchi.db import enums
from parchi.db.base import Base
from parchi.db.models import ALL_TABLES

MIGRATION = Path(__file__).parents[2] / "migrations" / "versions" / "0001_initial_schema.py"


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(f"migration_{path.stem}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_initial_migration():
    return _load(MIGRATION)


def latest_snapshot(name: str) -> tuple[str, ...]:
    """A list of allowed values as the newest migration that sets it leaves it."""
    found = None
    for path in sorted(MIGRATION.parent.glob("[0-9][0-9][0-9][0-9]_*.py")):
        found = getattr(_load(path), name, found)
    assert found is not None, name
    return tuple(found)


def values(enum_cls: type[StrEnum]) -> tuple[str, ...]:
    return tuple(member.value for member in enum_cls)


def test_every_table_has_timestamps() -> None:
    for table in Base.metadata.sorted_tables:
        for column in ("created_at", "updated_at"):
            assert column in table.columns, f"{table.name} has no {column}"
            assert not table.columns[column].nullable


def test_every_foreign_key_column_is_indexed() -> None:
    for table in Base.metadata.sorted_tables:
        # Expression indexes such as lower(name) have no plain columns.
        leading = {next(iter(ix.columns.keys())) for ix in table.indexes if ix.columns}
        leading |= {
            next(iter(c.columns.keys()))
            for c in table.constraints
            if c.__class__.__name__ == "UniqueConstraint"
        }
        for fk in table.foreign_key_constraints:
            assert fk.column_keys[0] in leading, f"{table.name}.{fk.column_keys[0]} not indexed"


def test_statuses_and_flag_types_match_decisions() -> None:
    assert "duplicate" not in values(enums.FileStatus)  # D-007
    assert "sequence_gap" not in values(enums.FlagType)  # D-008
    assert "out_of_order" not in values(enums.FlagType)  # D-008
    assert enums.BUILTIN_CATEGORIES == (
        "Fuel",
        "Travel",
        "Food",
        "Office",
        "Utilities",
        "Maintenance",
        "Services",
        "Other",
    )  # D-009, now rows in the categories table (D-026)


@pytest.mark.parametrize(
    ("snapshot", "enum_cls"),
    [
        ("FILE_STATUSES", enums.FileStatus),
        ("FILE_KINDS", enums.FileKind),
        ("RUN_PARSERS", enums.RunParser),
        ("AI_PROVIDERS", enums.AiProvider),
        ("FLAG_TYPES", enums.FlagType),
        ("FLAG_SEVERITIES", enums.FlagSeverity),
        ("USER_ROLES", enums.UserRole),
    ],
)
def test_migration_enum_snapshot_matches_code(snapshot: str, enum_cls: type[StrEnum]) -> None:
    """If this fails, an enum changed without a migration that updates its CHECK constraint."""
    assert latest_snapshot(snapshot) == values(enum_cls)


def test_library_parsers_snapshot_matches_code() -> None:
    assert load_initial_migration().LIBRARY_PARSERS == tuple(p.value for p in enums.LIBRARY_PARSERS)


def test_migrations_create_every_table() -> None:
    # 0001 created the original seven; 0002 added categories (D-026); 0006 users and
    # sessions (D-043); 0007 vendor_labels (D-048).
    later = {"categories", "users", "sessions", "vendor_labels"}
    assert set(load_initial_migration().TABLES) | later == set(ALL_TABLES)


def test_the_categories_migration_seeds_the_builtin_list() -> None:
    spec = importlib.util.spec_from_file_location(
        "categories_migration", MIGRATION.parent / "0002_categories_table.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.BUILTIN == enums.BUILTIN_CATEGORIES
    # The old text values were the built-in names in lower case.
    assert tuple(n.lower() for n in module.BUILTIN) == load_initial_migration().CATEGORIES
