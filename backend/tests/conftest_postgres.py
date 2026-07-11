"""PostgreSQL test fixtures (T015).

PostgreSQL-specific behavior (FOR UPDATE SKIP LOCKED dispatch leasing, real
concurrency) can only be exercised against Postgres. These fixtures are opt-in:
they skip unless HARNESS_TEST_POSTGRES_URL points at a disposable database (CI
provides one). Each test gets a freshly migrated schema and drops it after, so
runs are isolated.

Import into a Postgres-only test with:
    from tests.conftest_postgres import pg_engine  # noqa: F401
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlmodel import SQLModel, create_engine

BACKEND = Path(__file__).resolve().parents[1]


def _pg_url() -> str | None:
    return os.environ.get("HARNESS_TEST_POSTGRES_URL")


@pytest.fixture()
def pg_engine():
    url = _pg_url()
    if not url:
        pytest.skip("set HARNESS_TEST_POSTGRES_URL to run PostgreSQL tests")

    # migrate a clean schema to head via Alembic (the production path)
    env = dict(os.environ, HARNESS_DATABASE_URL=url)
    engine = create_engine(url)
    _drop_all(engine)
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
        cwd=BACKEND, env=env, check=True, capture_output=True,
    )
    try:
        yield engine
    finally:
        _drop_all(engine)
        engine.dispose()


def _drop_all(engine) -> None:
    # drop everything, including alembic_version, for a clean slate
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    SQLModel.metadata.clear()
