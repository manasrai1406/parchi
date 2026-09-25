"""Fixtures for tests that need a real PostgreSQL.

Set TEST_DATABASE_URL to a database whose name ends in `_test`; its public schema is
dropped and rebuilt. Without it, or if the server is down, these tests are skipped.
"""

import os
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, create_engine, make_url, text

from parchi.config import to_async_url

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def alembic_config(url: str) -> Config:
    config = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    config.attributes["database_url"] = url
    config.attributes["configure_logger"] = False
    return config


@pytest.fixture(scope="session")
def database_url() -> str:
    raw = os.environ.get("TEST_DATABASE_URL")
    if not raw:
        pytest.skip("TEST_DATABASE_URL is not set")
    url = to_async_url(raw)
    if not (make_url(url).database or "").endswith("_test"):
        pytest.fail("TEST_DATABASE_URL must point at a database whose name ends in _test")
    return url


@pytest.fixture(scope="session")
def engine(database_url: str) -> Iterator[Engine]:
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"PostgreSQL at TEST_DATABASE_URL is not reachable ({type(exc).__name__})")
    yield engine
    engine.dispose()


def reset_schema(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))


@pytest.fixture(scope="session")
def migrated(engine: Engine, database_url: str) -> str:
    reset_schema(engine)
    command.upgrade(alembic_config(database_url), "head")
    return database_url


@pytest.fixture
def alembic_cfg(migrated: str) -> Config:
    return alembic_config(migrated)


@pytest.fixture
def conn(engine: Engine, migrated: str) -> Iterator[Connection]:
    """A connection inside a transaction that is rolled back after the test."""
    with engine.connect() as connection:
        transaction = connection.begin()
        yield connection
        transaction.rollback()


def _clear_app_caches() -> None:
    from parchi.api import deps
    from parchi.config import get_settings
    from parchi.db import session as db_session

    get_settings.cache_clear()
    db_session.get_engine.cache_clear()
    db_session.get_sessionmaker.cache_clear()
    deps._storage_for.cache_clear()


@pytest.fixture
def storage_dir(tmp_path) -> str:
    return str(tmp_path / "uploads")


@pytest.fixture
def api(engine: Engine, migrated: str, storage_dir: str, monkeypatch: pytest.MonkeyPatch):
    """A TestClient for the real app, on an emptied test database and a temporary storage dir."""
    import asyncio
    import sys

    from fastapi.testclient import TestClient

    from parchi.api.main import create_app
    from parchi.db.models import ALL_TABLES

    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE {', '.join(ALL_TABLES)} RESTART IDENTITY CASCADE"))
        connection.execute(text("ALTER SEQUENCE file_ref_seq RESTART"))

    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", migrated)
    monkeypatch.setenv("STORAGE_DIR", storage_dir)
    monkeypatch.setenv("LOG_DIR", "")
    _clear_app_caches()
    # Uploads queue files for the worker; tests record the calls instead of using Redis.
    queued: list[int] = []

    async def record(file_id: int) -> None:
        queued.append(file_id)

    monkeypatch.setattr("parchi.api.routes.batches.queue_file", record)

    # psycopg's async mode cannot run on Windows' default Proactor event loop.
    options = {"loop_factory": asyncio.SelectorEventLoop} if sys.platform == "win32" else {}
    with TestClient(create_app(), backend_options=options) as client:
        client.queued = queued  # type: ignore[attr-defined]
        yield client
    _clear_app_caches()
