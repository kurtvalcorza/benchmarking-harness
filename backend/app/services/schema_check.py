"""Schema-revision readiness (T009/T014).

Production must run against a database migrated to the Alembic head — never
`create_all`, which silently masks a missing migration. This module reports the
schema status and, in production, refuses startup on a stale/unknown schema.

The offline SQLite demo and the test suite keep using `create_all` (repositories
handles the branch); for them the schema is defined as `current` because
`create_all` builds it directly from the ORM metadata.

Usage:
    python -m app.services.schema_check   # prints status, exits non-zero if stale
"""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from app.services.config import AppConfig, load_config

BACKEND = Path(__file__).resolve().parents[2]
ALEMBIC_INI = BACKEND / "alembic.ini"


def _alembic_config() -> Config:
    cfg = Config(str(ALEMBIC_INI))
    # resolve script_location absolutely so this works regardless of cwd
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    return cfg


def head_revision() -> str | None:
    script = ScriptDirectory.from_config(_alembic_config())
    return script.get_current_head()


def current_revision(engine) -> str | None:
    with engine.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


def schema_status(engine, cfg: AppConfig | None = None) -> str:
    """Return 'current' | 'stale' | 'unknown'."""
    cfg = cfg or load_config()
    if cfg.database_url.startswith("sqlite"):
        # create_all mode: the schema is built straight from the ORM metadata.
        return "current"
    try:
        current = current_revision(engine)
    except Exception:
        return "unknown"
    if current is None:
        return "unknown"
    return "current" if current == head_revision() else "stale"


def assert_production_schema_ready(engine, cfg: AppConfig | None = None) -> None:
    cfg = cfg or load_config()
    if not cfg.is_production:
        return
    status = schema_status(engine, cfg)
    if status != "current":
        raise RuntimeError(
            f"database schema is '{status}', not migrated to head {head_revision()!r}; "
            "run `alembic upgrade head` before starting in production "
            "(create_all is disabled in production)"
        )


def main() -> int:
    from app.db.repositories import get_engine

    engine = get_engine()
    status = schema_status(engine)
    print(f"schema: {status} (head={head_revision()})")
    return 0 if status == "current" else 1


if __name__ == "__main__":
    raise SystemExit(main())
