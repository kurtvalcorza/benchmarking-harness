"""T048 [US4] — durable dispatch survives a broker outage and duplicate delivery.

The submission's evaluation intent is written in the SAME transaction as the
model version (transactional outbox), so a lost in-request publish does not
strand the work: the dispatcher republishes the durable pending intent. A
duplicate transport delivery of a completed intent performs no new evaluation.
"""

from sqlmodel import Session, select

from app.db.enums import JobReason, JobState
from app.db.models import JobIntent
from app.db.repositories import get_engine
from app.services import dispatcher, orchestrator
from tests.conftest import HEALTHY_DET, det_manifest, register_golden, submit_model


def _boom(*_a, **_k):
    raise RuntimeError("broker down")


def test_submission_survives_broker_outage_and_dispatcher_recovers(client, monkeypatch):
    register_golden(client, det_manifest())
    broker = {"down": True}
    real_dispatch = orchestrator.dispatch_intent
    monkeypatch.setattr(
        orchestrator,
        "dispatch_intent",
        lambda iid, vid: _boom() if broker["down"] else real_dispatch(iid, vid),
    )

    # broker is down during the request: the submission still commits (201, no
    # 503) and the durable intent is left pending
    mv = submit_model(client, weights_path=HEALTHY_DET, name="outage", sources=["s"])
    assert mv["status"] == "pending"
    with Session(get_engine()) as s:
        intent = s.exec(
            select(JobIntent).where(
                JobIntent.model_version_id == mv["id"],
                JobIntent.reason == JobReason.submission,
            )
        ).first()
        assert intent is not None and intent.state is JobState.pending

    # broker recovers; a dispatcher sweep republishes the pending intent → the
    # evaluation runs and the healthy model approves
    broker["down"] = False
    published = dispatcher.dispatch_pending()
    assert intent.id in published
    assert client.get(f"/models/{mv['id']}").json()["status"] == "approved"
    with Session(get_engine()) as s:
        assert s.get(JobIntent, intent.id).state is JobState.completed


def test_duplicate_delivery_performs_no_new_evaluation(client):
    register_golden(client, det_manifest())
    mv = submit_model(client, weights_path=HEALTHY_DET, name="dup", sources=["s"])
    assert mv["status"] == "approved"
    with Session(get_engine()) as s:
        intent = s.exec(
            select(JobIntent).where(
                JobIntent.model_version_id == mv["id"],
                JobIntent.reason == JobReason.submission,
            )
        ).first()
        iid = intent.id

    before = client.get(f"/models/{mv['id']}/history").json()
    # a redelivery of the already-completed intent is a no-op
    assert orchestrator.evaluate_intent(iid) is None
    after = client.get(f"/models/{mv['id']}/history").json()
    assert len(before) == len(after) == 1
