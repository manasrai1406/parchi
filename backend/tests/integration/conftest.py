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
