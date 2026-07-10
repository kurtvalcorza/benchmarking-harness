"""T009 — the repository layer rejects update/delete on append-only entities."""

import pytest
from sqlmodel import Session

from app.db.enums import Verdict
from app.db.models import AuditEvent, EvaluationRun, Model, ModelVersion
from app.db.repositories import AppendOnlyViolation, get_engine, reset_engine


@pytest.fixture()
def session(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_DATABASE_URL", f"sqlite:///{tmp_path}/ao.db")
    reset_engine()
    with Session(get_engine()) as s:
        yield s
    reset_engine()


def _run(session) -> EvaluationRun:
    m = Model(name="m", model_class="detection")
    session.add(m)
    session.flush()
    mv = ModelVersion(model_id=m.id, version="v1", artifact_ref="/x", framework="stub")
    session.add(mv)
    session.flush()
    run = EvaluationRun(model_version_id=mv.id, verdict=Verdict.passed)
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def test_update_rejected(session):
    run = _run(session)
    run.verdict = Verdict.fail
    session.add(run)
    with pytest.raises(AppendOnlyViolation):
        session.commit()
    session.rollback()


def test_delete_rejected(session):
    run = _run(session)
    session.delete(run)
    with pytest.raises(AppendOnlyViolation):
        session.commit()
    session.rollback()


def test_audit_events_append_only(session):
    ev = AuditEvent(actor="x", action="access", target_ref="t")
    session.add(ev)
    session.commit()
    ev.action = "tampered"
    session.add(ev)
    with pytest.raises(AppendOnlyViolation):
        session.commit()
    session.rollback()


def test_mutable_entities_still_update(session):
    run = _run(session)
    mv = session.get(ModelVersion, run.model_version_id)
    mv.status = "evaluating"
    session.add(mv)
    session.commit()  # no exception: ModelVersion is not append-only
