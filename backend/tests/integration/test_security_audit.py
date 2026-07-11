"""T028 (US1): allowed and denied lifecycle operations are audited with identity.

A successful privileged change records the principal key and issuer; the audit
log never contains a bearer token.
"""

from sqlmodel import Session, select

from app.db.models import AuditEvent
from app.db.repositories import get_engine
from tests.conftest import HEALTHY_DET, bearer, det_manifest


def _audit_events(action_prefix: str) -> list[AuditEvent]:
    with Session(get_engine()) as s:
        return [
            e
            for e in s.exec(select(AuditEvent)).all()
            if e.action.startswith(action_prefix)
        ]


def test_submission_records_principal_identity(client):
    client.post("/golden-sets", json=det_manifest(), headers=bearer("g", ["governance"]))
    alice = bearer("alice@example.com", ["submitter"])
    with open(HEALTHY_DET, "rb") as f:
        r = client.post(
            "/models",
            data={"name": "audited", "model_class": "detection", "framework": "stub", "version": "v1"},
            files={"weights": (HEALTHY_DET.name, f, "application/json")},
            headers=alice,
        )
    assert r.status_code == 201
    events = _audit_events("model-version-submitted")
    assert events, "submission must be audited"
    ev = events[-1]
    assert ev.actor == "harness-dev|alice@example.com"
    assert ev.principal_issuer == "harness-dev"
    assert ev.outcome == "success"


def test_no_token_or_header_is_ever_stored_in_audit(client):
    client.post("/golden-sets", json=det_manifest(), headers=bearer("g", ["governance"]))
    with Session(get_engine()) as s:
        for e in s.exec(select(AuditEvent)).all():
            blob = f"{e.actor}{e.action}{e.target_ref}{e.audit_metadata}"
            assert "Bearer" not in blob and "eyJ" not in blob  # no JWT header prefix
