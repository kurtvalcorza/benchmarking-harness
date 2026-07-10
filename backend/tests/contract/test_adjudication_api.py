"""T038 — adjudication queue + decision endpoint contract (FR-012/013)."""

from tests.conftest import WEAK_DET, det_manifest, register_golden, submit_model


def _flagged_run(client) -> tuple[dict, dict]:
    register_golden(client, det_manifest())
    mv = submit_model(client, weights_path=WEAK_DET, name="weak", sources=["synthetic v1"])
    assert mv["status"] == "pending_adjudication"
    queue = client.get("/adjudication/queue").json()
    assert queue, "flagged run must appear in the queue"
    return mv, queue[0]


def test_queue_item_carries_trigger_and_evidence(client):
    _, item = _flagged_run(client)
    assert "safety_critical_recall_below_floor" in item["trigger"]
    assert item["evidence_ref"], "evidence must be reviewable without re-running (FR-012)"
    assert item["model_version_id"]


def test_decision_records_and_transitions(client):
    mv, item = _flagged_run(client)
    r = client.post(
        f"/adjudication/{item['run_id']}/decision",
        json={
            "reviewer": "adjudicator@example.com",
            "decision": "reject",
            "rationale": "pedestrian recall below floor in all conditions",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "rejected"
    assert client.get(f"/models/{mv['id']}").json()["status"] == "rejected"
    # queue drained
    assert client.get("/adjudication/queue").json() == []


def test_approve_via_decision_is_allowed_and_recorded(client):
    mv, item = _flagged_run(client)
    r = client.post(
        f"/adjudication/{item['run_id']}/decision",
        json={
            "reviewer": "adjudicator@example.com",
            "decision": "approve",
            "rationale": "acceptable for the limited pilot deployment",
        },
    )
    assert r.status_code == 200
    detail = client.get(f"/models/{mv['id']}").json()
    assert detail["status"] == "approved"
    # the decision is on the permanent record: card carries the adjudication block
    assert "adjudicator@example.com" in detail["card_markdown"]


def test_missing_rationale_is_422(client):
    _, item = _flagged_run(client)
    r = client.post(
        f"/adjudication/{item['run_id']}/decision",
        json={"reviewer": "r", "decision": "approve", "rationale": ""},
    )
    assert r.status_code == 422


def test_second_decision_is_409(client):
    _, item = _flagged_run(client)
    ok = client.post(
        f"/adjudication/{item['run_id']}/decision",
        json={"reviewer": "r", "decision": "reject", "rationale": "x"},
    )
    assert ok.status_code == 200
    again = client.post(
        f"/adjudication/{item['run_id']}/decision",
        json={"reviewer": "r", "decision": "approve", "rationale": "y"},
    )
    assert again.status_code == 409  # a decided run cannot be re-decided

def test_unknown_run_404(client):
    r = client.post(
        "/adjudication/nope/decision",
        json={"reviewer": "r", "decision": "approve", "rationale": "x"},
    )
    assert r.status_code == 404
