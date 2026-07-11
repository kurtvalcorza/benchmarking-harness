"""T037 — Scenario B: safety-critical failure → flagged → human decision → rejected.
Constitution I end-to-end."""

from tests.conftest import WEAK_DET, det_manifest, register_golden, submit_model


def test_flagged_to_pending_to_reject_flow(client):
    register_golden(client, det_manifest())
    mv = submit_model(
        client, weights_path=WEAK_DET, name="weak-detector", sources=["synthetic v1"]
    )
    # 1. flagged, never auto-approved (SC-002)
    assert mv["status"] == "pending_adjudication"

    runs = client.get(f"/models/{mv['id']}/history").json()
    run = client.get(f"/runs/{runs[0]['id']}").json()
    assert run["verdict"] == "pending_adjudication"
    assert "safety_critical_recall_below_floor" in run["flag_trigger"]

    # 2. evidence attached and reviewable without re-running
    queue = client.get("/adjudication/queue").json()
    item = next(q for q in queue if q["model_version_id"] == mv["id"])
    assert item["evidence_ref"]
    t2 = [t for t in run["tier_results"] if t["tier"] == "domain_stress"]
    breaches = [
        (t["condition"], cls, row)
        for t in t2
        for cls, row in t["metrics"]["safety_critical"].items()
        if not row["ok"]
    ]
    assert breaches, "the flag must be backed by a concrete per-class breach"

    # 3. recorded human decision moves it — and is permanent
    r = client.post(
        f"/adjudication/{item['run_id']}/decision",
        json={
            "reviewer": "adjudicator@example.com",
            "decision": "reject",
            "rationale": "pedestrian recall below the ratified floor; not deployable",
        },
    )
    assert r.status_code == 200
    detail = client.get(f"/models/{mv['id']}").json()
    assert detail["status"] == "rejected"
    card = detail["card_markdown"]
    assert "reject" in card and "adjudicator@example.com" in card  # FR-013 on the record
    # regeneration after the decision must recover the recorded isolation
    # evidence, not downgrade it (conftest runs the subprocess sandbox)
    assert "sandbox: subprocess" in card
    assert "sandbox: to be confirmed" not in card
