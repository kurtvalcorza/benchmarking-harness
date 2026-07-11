"""T049 [US4] — JobIntent claim idempotency.

A duplicate transport delivery must never yield a second concurrent claim, a
`completed` intent can never be reclaimed, and an expired lease is reclaimable.
On PostgreSQL the dispatcher's pending scan additionally takes
``FOR UPDATE SKIP LOCKED`` row locks (exercised by the CI Postgres migration
job); the claim-state logic proven here is dialect-independent.
"""

from datetime import timedelta

from sqlmodel import Session

from app.db.enums import JobReason, JobState
from app.db.models import JobIntent, utcnow
from app.db.repositories import get_engine
from app.services import dispatcher, jobs
from tests.conftest import HEALTHY_DET, submit_model


def _version_id(client, name: str) -> str:
    # a submission with no golden set infra-fails and leaves the version pending;
    # we only need a real ModelVersion FK target for the intents below
    return submit_model(client, weights_path=HEALTHY_DET, name=name, sources=["s"])["id"]


def _fresh_intent(version_id: str, occasion: str) -> str:
    with Session(get_engine()) as s:
        intent = jobs.create_intent(
            s,
            model_version_id=version_id,
            reason=JobReason.operator_retry,
            occasion=occasion,
        )
        s.commit()
        return intent.id


def test_second_claim_while_leased_is_a_duplicate(client):
    iid = _fresh_intent(_version_id(client, "claim-a"), "one")
    first = jobs.claim_intent(iid, worker_id="worker-A")
    assert first is not None
    # a second delivery finds a live lease → duplicate, runs NO evaluation
    assert jobs.claim_intent(iid, worker_id="worker-B") is None


def test_completed_intent_cannot_be_reclaimed(client):
    iid = _fresh_intent(_version_id(client, "claim-b"), "two")
    claim = jobs.claim_intent(iid, worker_id="worker-A")
    with Session(get_engine()) as s:
        jobs.complete_intent(s, iid, claim.attempt_id, run_id=None)
        s.commit()
    assert jobs.claim_intent(iid, worker_id="worker-B") is None
    with Session(get_engine()) as s:
        assert s.get(JobIntent, iid).state is JobState.completed


def test_expired_lease_is_reclaimed_then_reclaimable(client):
    iid = _fresh_intent(_version_id(client, "claim-c"), "three")
    jobs.claim_intent(iid, worker_id="worker-A")
    # simulate the worker dying mid-run: force its lease into the past
    with Session(get_engine()) as s:
        intent = s.get(JobIntent, iid)
        intent.leased_until = utcnow() - timedelta(seconds=1)
        s.add(intent)
        s.commit()
    assert dispatcher.reclaim_expired_leases() >= 1
    with Session(get_engine()) as s:
        assert s.get(JobIntent, iid).state is JobState.pending
    # a healthy worker can now claim the reclaimed intent
    assert jobs.claim_intent(iid, worker_id="worker-B") is not None


def test_duplicate_create_returns_the_same_intent(client):
    vid = _version_id(client, "claim-d")
    with Session(get_engine()) as s:
        a = jobs.create_intent(
            s, model_version_id=vid, reason=JobReason.golden_set_update, golden_set_id="gs1"
        )
        b = jobs.create_intent(
            s, model_version_id=vid, reason=JobReason.golden_set_update, golden_set_id="gs1"
        )
        s.commit()
        assert a.id == b.id  # deterministic idempotency key collapses the two
