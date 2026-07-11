"""T047 [US4] — adjudication is atomic.

The AdjudicationRecord, the status change, the audit event, and the regenerated
Model Card commit in ONE transaction (data-model.md §Successful adjudication). A
fault at the card/commit boundary must leave the decision UNRECORDED and the
model still awaiting adjudication — a reviewer must never see a "decided" model
whose card/lineage did not persist.
"""

import pytest
from sqlmodel import Session, select

from app.api import adjudication
from app.db.models import AdjudicationRecord
from app.db.repositories import get_engine
from tests.conftest import WEAK_DET, det_manifest, register_golden, submit_model


def _boom(*_a, **_k):
    raise RuntimeError("card render boom")


def _queue_a_weak_model(client) -> tuple[str, str]:
    register_golden(client, det_manifest())
    mv = submit_model(client, weights_path=WEAK_DET, name="adj-atomic", sources=["s"])
    assert mv["status"] == "pending_adjudication"
    queue = client.get("/adjudication/queue").json()
    run_id = next(item["run_id"] for item in queue if item["model_version_id"] == mv["id"])
    return mv["id"], run_id


def test_adjudication_card_failure_rolls_back_the_decision(client, monkeypatch):
    version_id, run_id = _queue_a_weak_model(client)
    # fault injected at card regeneration INSIDE the decision transaction
    monkeypatch.setattr(adjudication, "_regenerate_card", _boom)

    with pytest.raises(RuntimeError, match="card render boom"):
        client.post(
            f"/adjudication/{run_id}/decision",
            json={"decision": "reject", "rationale": "unsafe"},
        )

    # the decision never committed: no record, still pending_adjudication, still queued
    with Session(get_engine()) as s:
        assert (
            s.exec(
                select(AdjudicationRecord).where(AdjudicationRecord.run_id == run_id)
            ).first()
            is None
        )
    assert client.get(f"/models/{version_id}").json()["status"] == "pending_adjudication"
    assert any(item["run_id"] == run_id for item in client.get("/adjudication/queue").json())


def test_successful_adjudication_commits_decision_and_card_together(client):
    version_id, run_id = _queue_a_weak_model(client)
    r = client.post(
        f"/adjudication/{run_id}/decision",
        json={"decision": "reject", "rationale": "pedestrian recall below floor"},
    )
    assert r.status_code == 200, r.text
    assert client.get(f"/models/{version_id}").json()["status"] == "rejected"
    # the card regenerated in the same transaction records the decision
    detail = client.get(f"/models/{version_id}").json()
    assert "reject" in (detail["card_markdown"] or "").lower()
