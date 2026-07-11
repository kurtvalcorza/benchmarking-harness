"""Object-scope authorization (Codex P1 fixes): run evidence + history.

Role gating alone is not enough — a governance/adjudicator token must only reach
runs it is related to, and history must not leak sibling versions owned by a
different submitter (security-boundary.md).
"""

from sqlmodel import Session, select

from app.db.models import AuditEvent
from app.db.repositories import get_engine
from tests.conftest import HEALTHY_DET, WEAK_DET, bearer, det_manifest


def _register(client, header=None):
    r = client.post("/golden-sets", json=det_manifest(), headers=header or bearer("g", ["governance"]))
    assert r.status_code in (201, 409, 422)
    return r


def _submit(client, name, header, weights=HEALTHY_DET, version="v1"):
    with open(weights, "rb") as f:
        r = client.post(
            "/models",
            data={"name": name, "model_class": "detection", "framework": "stub", "version": version},
            files={"weights": (weights.name, f, "application/json")},
            headers=header,
        )
    assert r.status_code == 201, r.text
    return r.json()


def test_history_does_not_leak_sibling_submitters_versions(client):
    """Two submitters share a model name/class (one Model, two versions). Each
    may see only their own version's runs."""
    _register(client)
    alice = bearer("alice@example.com", ["submitter"])
    bob = bearer("bob@example.com", ["submitter"])
    a = _submit(client, "shared", alice, version="v1")
    _submit(client, "shared", bob, weights=WEAK_DET, version="v2")

    alice_history = client.get(f"/models/{a['id']}/history", headers=alice)
    assert alice_history.status_code == 200
    vids = {run["model_version_id"] for run in alice_history.json()}
    assert vids <= {a["id"]}, "history leaked another submitter's version runs"


def test_governance_cannot_read_unrelated_run(client):
    """A governance token that did not register the run's golden set (and any
    adjudicator without a related flagged case) is object-denied on /runs."""
    _register(client, header=bearer("owner@example.com", ["governance"]))
    mv = _submit(client, "scoped", bearer("s@example.com", ["submitter"]))
    run_id = client.get(f"/models/{mv['id']}/history", headers=bearer("u", ["auditor"])).json()[0]["id"]

    # a DIFFERENT governance principal did not register the golden set → 403
    other_gov = client.get(f"/runs/{run_id}", headers=bearer("other@example.com", ["governance"]))
    assert other_gov.status_code == 403
    # auditor may read any run
    assert client.get(f"/runs/{run_id}", headers=bearer("u", ["auditor"])).status_code == 200


def test_submitter_reads_own_run_details(client):
    """A submitter can read /runs/{id} for a run of their OWN model version, but
    not another submitter's run (Feature 002 contract includes submitter)."""
    _register(client)
    alice = bearer("alice@example.com", ["submitter"])
    bob = bearer("bob@example.com", ["submitter"])
    mv = _submit(client, "own-run", alice)
    run_id = client.get(f"/models/{mv['id']}/history", headers=alice).json()[0]["id"]
    assert client.get(f"/runs/{run_id}", headers=alice).status_code == 200
    assert client.get(f"/runs/{run_id}", headers=bob).status_code == 403


def test_governance_can_read_run_from_its_own_registration(client):
    owner = bearer("owner@example.com", ["governance"])
    _register(client, header=owner)
    mv = _submit(client, "owned", bearer("s@example.com", ["submitter"]))
    run_id = client.get(f"/models/{mv['id']}/history", headers=bearer("u", ["auditor"])).json()[0]["id"]
    # the governance user who registered the golden set the run used may read it
    assert client.get(f"/runs/{run_id}", headers=owner).status_code == 200


def test_denied_authorization_is_audited(client):
    # a submitter attempting a governance-only registration is denied AND audited
    r = client.post("/golden-sets", json=det_manifest(), headers=bearer("mallory@example.com", ["submitter"]))
    assert r.status_code == 403
    with Session(get_engine()) as s:
        denials = [
            e for e in s.exec(select(AuditEvent)).all()
            if e.action == "authorization-denied" and e.outcome == "denied"
        ]
    assert denials, "a denied privileged attempt must emit audit telemetry (FR-005)"
    assert denials[-1].actor == "harness-dev|mallory@example.com"
