"""T009: production refuses a stale/unknown schema; dev create_all reports current.

`assert_production_schema_ready` fails closed when the database is not migrated
to the Alembic head, so a missing migration cannot be papered over by create_all.
"""

import os

import pytest
from sqlalchemy import create_engine

from app.services.config import load_config
from app.services.schema_check import assert_production_schema_ready, head_revision, schema_status


def _clear(monkeypatch):
    for k in list(os.environ):
        if k.startswith("HARNESS_"):
            monkeypatch.delenv(k, raising=False)


def test_head_revision_is_the_hardening_migration():
    assert head_revision() == "0002_production_hardening"


def test_dev_sqlite_is_reported_current(monkeypatch, tmp_path):
    _clear(monkeypatch)
    monkeypatch.setenv("HARNESS_DATABASE_URL", f"sqlite:///{tmp_path}/x.db")
    cfg = load_config()
    engine = create_engine(cfg.database_url)
    assert schema_status(engine, cfg) == "current"


def test_production_unknown_schema_refuses_startup(monkeypatch, tmp_path):
    # a production posture pointed at an unmigrated sqlite-shaped URL: no
    # alembic_version → 'unknown' → refuse. (We use sqlite as a stand-in DB with
    # a non-sqlite-classified check by forcing production rules.)
    _clear(monkeypatch)
    monkeypatch.setenv("HARNESS_ENV", "production")
    monkeypatch.setenv("HARNESS_AUTH_MODE", "oidc")
    monkeypatch.setenv("HARNESS_OIDC_ISSUER", "https://issuer.example")
    monkeypatch.setenv("HARNESS_OIDC_AUDIENCE", "harness")
    # a postgres-classified URL string so schema_status does not take the sqlite
    # shortcut; the engine itself is never connected because current_revision
    # will fail → 'unknown'
    monkeypatch.setenv(
        "HARNESS_DATABASE_URL", "postgresql+psycopg://nouser:nopass@127.0.0.1:1/none"
    )
    cfg = load_config()
    engine = create_engine(cfg.database_url)
    with pytest.raises(RuntimeError, match="schema"):
        assert_production_schema_ready(engine, cfg)
