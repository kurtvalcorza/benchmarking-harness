"""T046 [US4] — evaluation completion is atomic.

The run, its TierResults, the status change, the audit events, the Model Card,
and the JobIntent completion commit in ONE transaction (data-model.md
§Successful evaluation completion). A fault at the card/evidence/commit boundary
must leave NONE of it visible — no half-approved model, no run without its card,
no published evidence for a rolled-back run.
"""

import hashlib
import os
from pathlib import Path

from sqlmodel import Session, select

from app.db.models import TierResult
from app.db.repositories import get_engine
from app.services import orchestrator
from tests.conftest import HEALTHY_DET, det_manifest, register_golden, submit_model


def _boom(*_a, **_k):
    raise RuntimeError("card render boom")


def test_card_failure_rolls_back_the_entire_run(client, monkeypatch):
    register_golden(client, det_manifest())
    # fault injected at the card-render step INSIDE the completion transaction
    monkeypatch.setattr(orchestrator, "_upsert_card", _boom)

    mv = submit_model(client, weights_path=HEALTHY_DET, name="atomic-fail", sources=["s"])

    # nothing from the failed completion is visible: no run, no card, and the
    # version is reset to `pending` (never stuck `evaluating`)
    assert mv["status"] == "pending"
    assert client.get(f"/models/{mv['id']}/history").json() == []
    assert client.get(f"/models/{mv['id']}").json()["card_markdown"] is None

    # and no evidence was published for the rolled-back run (compensation)
    runs_dir = Path(os.environ["HARNESS_RESULTS_DIR"]) / "runs"
    assert not runs_dir.exists() or not any(runs_dir.iterdir())
    staging_dir = Path(os.environ["HARNESS_RESULTS_DIR"]) / "staging"
    assert not staging_dir.exists() or not any(staging_dir.iterdir())


def test_committed_run_has_matching_published_evidence(client):
    register_golden(client, det_manifest())
    mv = submit_model(client, weights_path=HEALTHY_DET, name="atomic-ok", sources=["s"])
    assert mv["status"] == "approved"

    hist = client.get(f"/models/{mv['id']}/history").json()
    assert len(hist) == 1
    run_id = hist[0]["id"]
    with Session(get_engine()) as s:
        results = s.exec(select(TierResult).where(TierResult.run_id == run_id)).all()
        assert results
        for tr in results:
            body = Path(tr.evidence_ref).read_bytes()  # evidence was published
            assert hashlib.sha256(body).hexdigest() == tr.evidence_digest  # digest matches
