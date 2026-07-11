"""T048 [US4] — durable dispatch survives a broker outage and duplicate delivery.

The submission's evaluation intent is written in the SAME transaction as the
model version (transactional outbox), so a lost in-request publish does not
strand the work: the dispatcher republishes the durable pending intent. A
duplicate transport delivery of a completed intent performs no new evaluation.
"""

from datetime import timedelta

from sqlmodel import Session, select

from app.db.enums import JobReason, JobState, ModelStatus
from app.db.models import JobIntent, ModelVersion, utcnow
from app.db.repositories import get_engine
from app.services import dispatcher, jobs, orchestrator
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


def test_worker_death_mid_run_is_recovered_not_poison_looped(client):
    """A worker that dies mid-run leaves the version stuck `evaluating` and its
    intent `claimed`. The dispatcher must reclaim the EXPIRED lease, release the
    stale `evaluating` mutex, and re-dispatch — recovering the version rather
    than poison-looping on an illegal evaluating→evaluating transition."""
    register_golden(client, det_manifest())
    mv = submit_model(client, weights_path=HEALTHY_DET, name="crash", sources=["s"])
    assert mv["status"] == "approved"

    # manufacture the dead-worker state: a fresh claimed intent whose lease has
    # expired, with the version wedged back to `evaluating`
    with Session(get_engine()) as s:
        intent = jobs.create_intent(
            s, model_version_id=mv["id"], reason=JobReason.operator_retry, occasion="crash"
        )
        s.commit()
        iid = intent.id
    jobs.claim_intent(iid, worker_id="dead-worker")
    with Session(get_engine()) as s:
        i = s.get(JobIntent, iid)
        i.leased_until = utcnow() - timedelta(seconds=1)  # lease expired (worker died)
        s.add(i)
        v = s.get(ModelVersion, mv["id"])
        v.status = ModelStatus.evaluating  # wedged mid-run
        s.add(v)
        s.commit()

    # reclaim releases the stale mutex...
    assert dispatcher.reclaim_expired_leases() >= 1
    with Session(get_engine()) as s:
        assert s.get(ModelVersion, mv["id"]).status is ModelStatus.pending
        assert s.get(JobIntent, iid).state is JobState.pending

    # ...and re-dispatch recovers the version (no poison loop)
    dispatcher.dispatch_pending()
    assert client.get(f"/models/{mv['id']}").json()["status"] == "approved"
    with Session(get_engine()) as s:
        assert s.get(JobIntent, iid).state is JobState.completed
