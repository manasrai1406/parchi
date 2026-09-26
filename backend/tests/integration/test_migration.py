"""The first migration against a real PostgreSQL: tables, and every rule the schema enforces."""

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Connection, Engine, inspect, text
from sqlalchemy.exc import IntegrityError

from parchi.db.base import Base
from parchi.db.models import ALL_TABLES

pytestmark = pytest.mark.db

SHA = "a" * 64


# --- helpers -------------------------------------------------------------------------


def insert(conn: Connection, sql: str, **params: object) -> int:
    return conn.execute(text(sql + " RETURNING id"), params).scalar_one()


def make_file(
    conn: Connection,
    ref_no: str = "REF-2026-000001",
    original_name: str = "bill.pdf",
    sha256: str = SHA,
    duplicate_of_id: int | None = None,
) -> int:
    batch_id = insert(conn, "INSERT INTO upload_batches DEFAULT VALUES")
    return insert(
        conn,
        "INSERT INTO files (ref_no, batch_id, original_name, sha256, size_bytes, storage_path,"
        " duplicate_of_id) VALUES (:ref_no, :batch_id, :original_name, :sha256, 10,"
        " :path, :duplicate_of_id)",
        ref_no=ref_no,
        batch_id=batch_id,
        original_name=original_name,
        sha256=sha256,
        path=f"{sha256[:2]}/{sha256}.pdf",
        duplicate_of_id=duplicate_of_id,
    )


def make_run(conn: Connection, file_id: int, parser: str = "pdf_text", **extra: object) -> int:
    columns = {"file_id": file_id, "parser": parser, **extra}
    names = ", ".join(columns)
    values = ", ".join(f":{name}" for name in columns)
    return insert(conn, f"INSERT INTO extraction_runs ({names}) VALUES ({values})", **columns)


def make_accepted_run(conn: Connection, file_id: int, parser: str = "pdf_text") -> int:
    return make_run(
        conn, file_id, parser, accepted=True, result_json="[]", finished_at="2026-09-26T10:00:00Z"
    )


def make_vendor(conn: Connection, raw_name: str = "HP PETROL PUMP") -> int:
    return insert(
        conn,
        "INSERT INTO vendors (raw_name, normalized_name) VALUES (:raw, 'HP Petrol Pump')",
        raw=raw_name,
    )


def make_receipt(
    conn: Connection, file_id: int, run_id: int, seq: int = 1, ref_no: str | None = None, **extra
) -> int:
    columns = {
        "file_id": file_id,
        "run_id": run_id,
        "seq": seq,
        "ref_no": ref_no or f"REF-2026-000001-{seq:02d}",
        "vendor_id": extra.pop("vendor_id", None) or make_vendor(conn, f"vendor {seq}"),
        "receipt_date": "2026-08-14",
        "total": "1234.50",
        **extra,
    }
    names = ", ".join(columns)
    values = ", ".join(f":{name}" for name in columns)
    return insert(conn, f"INSERT INTO receipts ({names}) VALUES ({values})", **columns)


@contextmanager
def rejected(conn: Connection) -> Iterator[None]:
    """Expect the statement inside to break a constraint; keep the outer transaction usable."""
    with pytest.raises(IntegrityError), conn.begin_nested():
        yield


# --- the migration itself ------------------------------------------------------------


def test_upgrade_creates_every_table(engine: Engine, migrated: str) -> None:
    tables = set(inspect(engine).get_table_names())
    assert tables == {*ALL_TABLES, "alembic_version"}


def test_models_match_the_migration(engine: Engine, migrated: str) -> None:
    with engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert diff == []


def test_downgrade_removes_everything_and_upgrade_restores_it(
    engine: Engine, alembic_cfg: Config
) -> None:
    config = alembic_cfg
    command.downgrade(config, "base")
    with engine.connect() as connection:
        assert set(inspect(connection).get_table_names()) == {"alembic_version"}
        assert (
            connection.execute(
                text("SELECT count(*) FROM pg_class WHERE relname = 'file_ref_seq'")
            ).scalar_one()
            == 0
        )
    command.upgrade(config, "head")
    assert set(ALL_TABLES) <= set(inspect(engine).get_table_names())


def test_reference_sequence_counts_up(conn: Connection) -> None:
    first = conn.execute(text("SELECT nextval('file_ref_seq')")).scalar_one()
    second = conn.execute(text("SELECT nextval('file_ref_seq')")).scalar_one()
    assert second == first + 1


def test_updated_at_is_set_by_trigger(conn: Connection) -> None:
    batch_id = insert(
        conn,
        "INSERT INTO upload_batches (created_at, updated_at)"
        " VALUES ('2000-01-01T00:00:00Z', '2000-01-01T00:00:00Z')",
    )
    conn.execute(
        text("UPDATE upload_batches SET created_at = created_at WHERE id = :id"), {"id": batch_id}
    )
    updated_at = conn.execute(
        text("SELECT updated_at > '2001-01-01T00:00:00Z' FROM upload_batches WHERE id = :id"),
        {"id": batch_id},
    ).scalar_one()
    assert updated_at is True


# --- files ---------------------------------------------------------------------------


def test_identical_hash_can_be_saved_when_linked_to_the_original(conn: Connection) -> None:
    original = make_file(conn)
    copy = make_file(conn, ref_no="REF-2026-000002", duplicate_of_id=original)  # D-006
    status = conn.execute(text("SELECT status FROM files WHERE id = :id"), {"id": copy})
    assert status.scalar_one() == "pending"


@pytest.mark.parametrize(
    "name", ["dir/bill.pdf", "dir\\bill.pdf", "bill\n.pdf", "bill\x07.pdf", ""]
)
def test_unsafe_file_names_are_rejected(conn: Connection, name: str) -> None:
    with rejected(conn):
        make_file(conn, original_name=name)


@pytest.mark.parametrize("ref_no", ["REF-26-000001", "REF-2026-1", "ref-2026-000001"])
def test_bad_file_reference_is_rejected(conn: Connection, ref_no: str) -> None:
    with rejected(conn):
        make_file(conn, ref_no=ref_no)


@pytest.mark.parametrize("status", ["duplicate", "done"])
def test_unknown_status_is_rejected(conn: Connection, status: str) -> None:
    file_id = make_file(conn)
    with rejected(conn):
        conn.execute(
            text("UPDATE files SET status = :s WHERE id = :id"), {"s": status, "id": file_id}
        )


def test_storage_path_must_be_relative(conn: Connection) -> None:
    file_id = make_file(conn)
    for path in ("/etc/passwd", "../outside.pdf"):
        with rejected(conn):
            conn.execute(
                text("UPDATE files SET storage_path = :p WHERE id = :id"),
                {"p": path, "id": file_id},
            )


# --- extraction runs -----------------------------------------------------------------


def test_only_one_accepted_run_per_file(conn: Connection) -> None:
    file_id = make_file(conn)
    make_accepted_run(conn, file_id)
    with rejected(conn):
        make_accepted_run(conn, file_id, parser="manual")


def test_only_one_library_run_per_file(conn: Connection) -> None:
    file_id = make_file(conn)
    make_run(conn, file_id, "pdf_text")
    with rejected(conn):
        make_run(conn, file_id, "pdf_scan")
    make_run(conn, file_id, "manual")
    make_run(conn, file_id, "manual")


def test_ai_run_without_approval_is_rejected(conn: Connection) -> None:
    file_id = make_file(conn)
    with rejected(conn):
        make_run(conn, file_id, "ai", provider="anthropic")
    with rejected(conn):
        make_run(
            conn, file_id, "ai", ai_approved_by="local user", ai_approved_at="2026-09-26T10:00:00Z"
        )


@pytest.mark.parametrize(
    ("provider", "model"),
    [
        ("anthropic", "claude-sonnet-5"),
        ("openai", "gpt-6-sol"),
        ("gemini", "gemini-3.6-flash"),  # D-041, migration 0005
    ],
)
def test_ai_run_with_approval_is_recorded(conn: Connection, provider: str, model: str) -> None:
    file_id = make_file(conn)
    run_id = make_run(
        conn,
        file_id,
        "ai",
        provider=provider,
        model=model,
        ai_approved_by="local user",
        ai_approved_at="2026-09-26T10:00:00Z",
    )
    row = conn.execute(
        text("SELECT provider, ai_approved_by FROM extraction_runs WHERE id = :id"), {"id": run_id}
    ).one()
    assert tuple(row) == (provider, "local user")


def test_an_unknown_ai_provider_is_rejected(conn: Connection) -> None:
    file_id = make_file(conn)
    with rejected(conn):
        make_run(
            conn,
            file_id,
            "ai",
            provider="mistral",
            model="m",
            ai_approved_by="local user",
            ai_approved_at="2026-09-26T10:00:00Z",
        )


def test_library_run_cannot_carry_ai_fields(conn: Connection) -> None:
    file_id = make_file(conn)
    with rejected(conn):
        make_run(conn, file_id, "pdf_text", provider="openai")


def test_failed_run_cannot_be_accepted(conn: Connection) -> None:
    file_id = make_file(conn)
    with rejected(conn):
        make_run(
            conn,
            file_id,
            accepted=True,
            error="timeout",
            result_json="[]",
            finished_at="2026-09-26T10:00:00Z",
        )


# --- receipts and line items ---------------------------------------------------------


def test_receipt_must_come_from_a_run_of_the_same_file(conn: Connection) -> None:
    file_a = make_file(conn)
    file_b = make_file(conn, ref_no="REF-2026-000002", sha256="b" * 64)
    run_b = make_accepted_run(conn, file_b)
    with rejected(conn):
        make_receipt(conn, file_a, run_b)


def test_receipt_reference_must_match_its_sequence(conn: Connection) -> None:
    file_id = make_file(conn)
    run_id = make_accepted_run(conn, file_id)
    make_receipt(conn, file_id, run_id, seq=1, ref_no="REF-2026-000001-01")
    make_receipt(conn, file_id, run_id, seq=123, ref_no="REF-2026-000001-123")
    with rejected(conn):
        make_receipt(conn, file_id, run_id, seq=2, ref_no="REF-2026-000001-03")
    with rejected(conn):
        make_receipt(conn, file_id, run_id, seq=4, ref_no="REF-2026-000001-4")


def category_id(conn: Connection, name: str) -> int:
    return conn.execute(
        text("SELECT id FROM categories WHERE lower(name) = lower(:n)"), {"n": name}
    ).scalar_one()


def test_builtin_categories_are_seeded(conn: Connection) -> None:
    names = conn.execute(text("SELECT name FROM categories WHERE builtin ORDER BY id")).scalars()
    assert list(names) == [
        "Fuel",
        "Travel",
        "Food",
        "Office",
        "Utilities",
        "Maintenance",
        "Services",
        "Other",
    ]


def test_category_names_are_unique_ignoring_case(conn: Connection) -> None:
    insert(conn, "INSERT INTO categories (name) VALUES ('Client visits')")
    with rejected(conn):
        insert(conn, "INSERT INTO categories (name) VALUES ('client VISITS')")
    for bad in ("", " padded ", "tab" + chr(9) + "here"):
        with rejected(conn):
            insert(conn, "INSERT INTO categories (name) VALUES (:n)", n=bad)


def test_category_override_wins(conn: Connection) -> None:
    file_id = make_file(conn)
    run_id = make_accepted_run(conn, file_id)
    fuel, travel = category_id(conn, "fuel"), category_id(conn, "travel")
    receipt_id = make_receipt(conn, file_id, run_id, category_auto_id=fuel)

    def effective() -> int | None:
        return conn.execute(
            text("SELECT category_id FROM receipts WHERE id = :id"), {"id": receipt_id}
        ).scalar_one()

    assert effective() == fuel
    conn.execute(
        text("UPDATE receipts SET category_override_id = :c WHERE id = :id"),
        {"c": travel, "id": receipt_id},
    )
    assert effective() == travel


def test_a_category_in_use_cannot_be_deleted(conn: Connection) -> None:
    file_id = make_file(conn)
    run_id = make_accepted_run(conn, file_id)
    custom = insert(conn, "INSERT INTO categories (name) VALUES ('Client visits')")
    make_receipt(conn, file_id, run_id, category_override_id=custom)
    with rejected(conn):
        conn.execute(text("DELETE FROM categories WHERE id = :id"), {"id": custom})


def test_deleting_a_receipt_removes_items_and_keeps_flags(conn: Connection) -> None:
    file_id = make_file(conn)
    run_id = make_accepted_run(conn, file_id)
    receipt_id = make_receipt(conn, file_id, run_id)
    insert(
        conn,
        "INSERT INTO line_items (receipt_id, position, description, amount)"
        " VALUES (:r, 1, 'Diesel', '1234.50')",
        r=receipt_id,
    )
    flag_id = insert(
        conn,
        "INSERT INTO flags (file_id, receipt_id, type, severity, detail, dedupe_key)"
        " VALUES (:f, :r, 'arithmetic_mismatch', 'warning', 'Items do not add up', 'k1')",
        f=file_id,
        r=receipt_id,
    )

    conn.execute(text("DELETE FROM receipts WHERE id = :id"), {"id": receipt_id})

    items = conn.execute(
        text("SELECT count(*) FROM line_items WHERE receipt_id = :id"), {"id": receipt_id}
    )
    assert items.scalar_one() == 0
    flag = conn.execute(text("SELECT receipt_id FROM flags WHERE id = :id"), {"id": flag_id})
    assert flag.scalar_one() is None


# --- flags ---------------------------------------------------------------------------


def test_open_flags_are_not_duplicated(conn: Connection) -> None:
    file_id = make_file(conn)
    sql = (
        "INSERT INTO flags (file_id, type, severity, detail, dedupe_key)"
        " VALUES (:f, 'duplicate_receipt', 'warning', 'Same receipt twice', 'dup:1:2')"
    )
    first = insert(conn, sql, f=file_id)
    with rejected(conn):
        insert(conn, sql, f=file_id)

    conn.execute(
        text(
            "UPDATE flags SET resolved = true, resolved_by = 'local user', resolved_at = now()"
            " WHERE id = :id"
        ),
        {"id": first},
    )
    insert(conn, sql, f=file_id)  # the same problem may be raised again once resolved


def test_resolution_fields_must_agree(conn: Connection) -> None:
    file_id = make_file(conn)
    with rejected(conn):
        insert(
            conn,
            "INSERT INTO flags (file_id, type, severity, detail, dedupe_key, resolved)"
            " VALUES (:f, 'unreadable', 'error', 'Cannot open', 'u:1', true)",
            f=file_id,
        )
