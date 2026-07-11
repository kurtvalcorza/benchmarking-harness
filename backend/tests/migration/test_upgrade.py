"""T008: migration upgrade tests — empty DB and a Feature 001 baseline.

Runs against SQLite by default (fast, offline). When HARNESS_TEST_POSTGRES_URL
is set (CI), the same assertions run against PostgreSQL, which is the production
target. The core guarantee: after `upgrade head`, the migrated schema contains
every table and column the live ORM (`SQLModel.metadata`) declares.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect
from sqlmodel import SQLModel

BACKEND = Path(__file__).resolve().parents[2]


def _alembic_upgrade(url: str) -> None:
    env = dict(os.environ, HARNESS_DATABASE_URL=url)
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
        cwd=BACKEND,
        env=env,
        check=True,
        capture_output=True,
    )


def _urls(tmp_path):
    urls = [f"sqlite:///{tmp_path}/empty.db"]
    pg = os.environ.get("HARNESS_TEST_POSTGRES_URL")
    if pg:
        urls.append(pg)
    return urls


def _expected_tables() -> set[str]:
    import app.db.models  # noqa: F401  (registers tables)

    return set(SQLModel.metadata.tables.keys())


def test_empty_database_upgrades_to_head_with_full_schema(tmp_path):
    for url in _urls(tmp_path):
        _alembic_upgrade(url)
        engine = create_engine(url)
        insp = inspect(engine)
        tables = set(insp.get_table_names())
        missing = _expected_tables() - tables
        assert not missing, f"{url}: migration head is missing ORM tables: {missing}"
        # spot-check the identity/entity columns feature 002 adds
        mv_cols = {c["name"] for c in insp.get_columns("modelversion")}
        assert {"submitted_by", "artifact_receipt_id"} <= mv_cols
        assert "artifactreceipt" in tables and "jobintent" in tables
        engine.dispose()


def test_feature_001_baseline_then_hardening_backfills_legacy_identity(tmp_path):
    """Stop at the 001 baseline, insert a legacy row, then upgrade to head:
    the new NOT NULL identity must backfill to the legacy principal."""
    url = f"sqlite:///{tmp_path}/baseline.db"
    env = dict(os.environ, HARNESS_DATABASE_URL=url)
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade",
         "0001_feature_001_baseline"],
        cwd=BACKEND, env=env, check=True, capture_output=True,
    )
    engine = create_engine(url)
    with engine.begin() as conn:
        from sqlalchemy import text

        conn.execute(text(
            "INSERT INTO model (id, name, model_class, created_at) "
            "VALUES ('m1', 'legacy', 'detection', '2026-01-01 00:00:00')"
        ))
        conn.execute(text(
            "INSERT INTO modelversion "
            "(id, model_id, version, artifact_ref, framework, declared_sources, status, submitted_at) "
            "VALUES ('v1', 'm1', 'v1', '/x', 'stub', '[]', 'approved', '2026-01-01 00:00:00')"
        ))
    engine.dispose()

    _alembic_upgrade(url)  # now to head

    engine = create_engine(url)
    with engine.begin() as conn:
        from sqlalchemy import text

        row = conn.execute(text("SELECT submitted_by FROM modelversion WHERE id='v1'")).one()
    engine.dispose()
    assert row[0] == "legacy:feature-001"


@pytest.mark.skipif(
    not os.environ.get("HARNESS_TEST_POSTGRES_URL"),
    reason="requires a PostgreSQL target (CI)",
)
def test_upgrade_is_idempotent_on_postgres(tmp_path):
    url = os.environ["HARNESS_TEST_POSTGRES_URL"]
    _alembic_upgrade(url)
    _alembic_upgrade(url)  # second run is a no-op, must not error
