"""T024 (US1): the recorded reviewer is the authenticated subject.

A client cannot self-assert reviewer identity: a `reviewer` field in the body is
ignored, and the AdjudicationRecord/card carry the token subject instead.
"""

from tests.conftest import WEAK_DET, bearer, det_manifest, register_golden, submit_model


def _flagged(client):
    register_golden(client, det_manifest())
    mv = submit_model(client, weights_path=WEAK_DET, name="weak-id", sources=["synthetic v1"])
    assert mv["status"] == "pending_adjudication"
    item = next(
        q for q in client.get("/adjudication/queue").json() if q["model_version_id"] == mv["id"]
    )
    return mv, item


def test_reviewer_is_token_subject_not_body(client):
    mv, item = _flagged(client)
    r = client.post(
        f"/adjudication/{item['run_id']}/decision",
        json={
            "reviewer": "impersonated@evil.example",  # must be ignored
            "decision": "reject",
            "rationale": "recall below floor",
        },
        headers=bearer("real-adjudicator@example.com", ["adjudicator"]),
    )
    assert r.status_code == 200
    card = client.get(f"/models/{mv['id']}").json()["card_markdown"]
    assert "real-adjudicator@example.com" in card
    assert "impersonated@evil.example" not in card


def test_decision_requires_adjudicator_role(client):
    _, item = _flagged(client)
    r = client.post(
        f"/adjudication/{item['run_id']}/decision",
        json={"decision": "reject", "rationale": "x"},
        headers=bearer("just-an-auditor@example.com", ["auditor"]),
    )
    assert r.status_code == 403  # auditor may read the queue but not decide
