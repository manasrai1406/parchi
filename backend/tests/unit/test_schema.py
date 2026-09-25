"""Checks on the table definitions that do not need a database."""

import importlib.util
from enum import StrEnum
from pathlib import Path

import pytest

from parchi.db import enums
from parchi.db.base import Base
from parchi.db.models import ALL_TABLES

MIGRATION = Path(__file__).parents[2] / "migrations" / "versions" / "0001_initial_schema.py"


def load_initial_migration():
    spec = importlib.util.spec_from_file_location("initial_migration", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def values(enum_cls: type[StrEnum]) -> tuple[str, ...]:
    return tuple(member.value for member in enum_cls)


def test_every_table_has_timestamps() -> None:
    for table in Base.metadata.sorted_tables:
        for column in ("created_at", "updated_at"):
            assert column in table.columns, f"{table.name} has no {column}"
            assert not table.columns[column].nullable


def test_every_foreign_key_column_is_indexed() -> None:
    for table in Base.metadata.sorted_tables:
        leading = {next(iter(ix.columns.keys())) for ix in table.indexes}
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
    assert values(enums.Category) == (
        "fuel",
        "travel",
        "food",
        "office",
        "utilities",
        "maintenance",
        "services",
        "other",
    )  # D-009


@pytest.mark.parametrize(
    ("snapshot", "enum_cls"),
    [
        ("FILE_STATUSES", enums.FileStatus),
        ("FILE_KINDS", enums.FileKind),
        ("RUN_PARSERS", enums.RunParser),
        ("AI_PROVIDERS", enums.AiProvider),
        ("FLAG_TYPES", enums.FlagType),
        ("FLAG_SEVERITIES", enums.FlagSeverity),
        ("CATEGORIES", enums.Category),
    ],
)
def test_migration_enum_snapshot_matches_code(snapshot: str, enum_cls: type[StrEnum]) -> None:
    """If this fails, an enum changed without a migration that updates its CHECK constraint."""
    assert getattr(load_initial_migration(), snapshot) == values(enum_cls)


def test_library_parsers_snapshot_matches_code() -> None:
    assert load_initial_migration().LIBRARY_PARSERS == tuple(p.value for p in enums.LIBRARY_PARSERS)


def test_migration_creates_every_table() -> None:
    assert set(load_initial_migration().TABLES) == set(ALL_TABLES)
