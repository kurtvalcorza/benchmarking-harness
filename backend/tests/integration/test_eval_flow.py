"""T023 — Scenario A: a healthy model flows pending → evaluating → approved,
with a stored result per tier and a populated Model Card."""

from tests.conftest import HEALTHY_DET, det_manifest, register_golden, submit_model


def test_healthy_model_approved_end_to_end(client):
    register_golden(client, det_manifest())
    mv = submit_model(
        client,
        weights_path=HEALTHY_DET,
        name="healthy-detector",
        sources=["synthetic training set v1 (owned)"],
    )
    assert mv["status"] == "approved", mv

    runs = client.get(f"/models/{mv['id']}/history").json()
    assert len(runs) == 1
    run = client.get(f"/runs/{runs[0]['id']}").json()
    assert run["verdict"] == "pass"
    assert run["infra_ok"] is True

    tiers = {t["tier"] for t in run["tier_results"]}
    assert tiers == {"capability", "domain_stress", "operational_safety"}  # FR-005

    # SC-009: per-tier reason visible from the stored result alone
    for t in run["tier_results"]:
        assert t["metrics"], f"tier {t['tier']} lost its metrics"
        if t["threshold"]:
            assert t["passed"] is True

    # golden-set contamination trail (FR-018)
    t2 = [t for t in run["tier_results"] if t["tier"] == "domain_stress"]
    assert all(t["dataset_checksum"] == run["golden_set"]["checksum"] for t in t2)

    # Model Card generated with machine blocks (US3)
    detail = client.get(f"/models/{mv['id']}").json()
    card = detail["card_markdown"]
    assert card and "## Benchmark Results" in card and "## Provenance" in card
    assert "synthetic training set v1 (owned)" in card


def test_tier1_failure_halts_and_records(client, tmp_path):
    """FR-007 + edge case: Tier 1 failure → no Tier 2/3, verdict fail, metric named."""
    import json

    hopeless = tmp_path / "hopeless.stub.json"
    hopeless.write_text(
        json.dumps({"kind": "stub-model", "task": "detection", "skill": 0.05, "grounding": 0.9})
    )
    register_golden(client, det_manifest())
    mv = submit_model(client, weights_path=hopeless, name="hopeless", sources=["s"])
    assert mv["status"] == "rejected"

    runs = client.get(f"/models/{mv['id']}/history").json()
    run = client.get(f"/runs/{runs[0]['id']}").json()
    tiers = [t["tier"] for t in run["tier_results"]]
    assert tiers == ["capability"]  # halted — Tier 2/3 skipped
    t1 = run["tier_results"][0]
    assert t1["passed"] is False
    assert t1["metrics"]["map_50_95"] is not None  # failing score still recorded
