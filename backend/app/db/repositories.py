"""Append-only enforcement + session helpers.

EvaluationRun / TierResult / AdjudicationRecord / AuditEvent may be inserted but
never updated or deleted (data-model.md 🔒, Constitution IV). Enforced globally
via a SQLAlchemy before_flush hook, which covers every ORM-tracked mutation.
Caveat: Core-level statements (session.execute(update(...)/delete(...))) do not
pass through the flush machinery and would bypass this guard — all persistence
MUST go through ORM instances, never raw update/delete statements.

EvaluationRun rows are inserted *complete* (verdict + finished_at set) by the
orchestrator — in-flight state is carried on ModelVersion.status, which is
mutable.
"""

import os

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

from app.db.models import APPEND_ONLY_TABLES


class AppendOnlyViolation(RuntimeError):
    """Raised when an update/delete is attempted on an append-only entity."""


@event.listens_for(Session, "before_flush")
def _reject_mutations(session, flush_context, instances):  # noqa: ANN001
    for obj in session.dirty:
        if isinstance(obj, APPEND_ONLY_TABLES) and session.is_modified(obj):
            raise AppendOnlyViolation(
                f"{type(obj).__name__} is append-only: update rejected (Constitution IV)"
            )
    for obj in session.deleted:
        if isinstance(obj, APPEND_ONLY_TABLES):
            raise AppendOnlyViolation(
                f"{type(obj).__name__} is append-only: delete rejected (Constitution IV)"
            )


def database_url() -> str:
    return os.environ.get("HARNESS_DATABASE_URL", "sqlite:///harness.db")


_engine = None


def get_engine():
    global _engine
    if _engine is None:
        url = database_url()
        kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
        _engine = create_engine(url, **kwargs)
        SQLModel.metadata.create_all(_engine)
    return _engine


def reset_engine() -> None:
    """Test helper: drop the cached engine so a new HARNESS_DATABASE_URL takes effect."""
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = None


def get_session():
    with Session(get_engine()) as session:
        yield session
