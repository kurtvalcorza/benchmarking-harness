"""T053 — multi-version append-only history (FR-016, US5)."""

from tests.conftest import HEALTHY_DET, WEAK_DET, det_manifest, register_golden, submit_model


def test_two_versions_both_runs_returned_in_order(client):
    register_golden(client, det_manifest())
    v1 = submit_model(
        client, weights_path=WEAK_DET, name="iterating-model", version="v1", sources=["s"]
    )
    v2 = submit_model(
        client, weights_path=HEALTHY_DET, name="iterating-model", version="v2", sources=["s"]
    )
    assert v1["model_id"] == v2["model_id"]

    # history is reachable from either version id and spans ALL versions
    history = client.get(f"/models/{v2['id']}/history").json()
    assert len(history) == 2
    assert history[0]["model_version_id"] == v1["id"]
    assert history[1]["model_version_id"] == v2["id"]
    assert history[0]["started_at"] <= history[1]["started_at"]

    # neither run overwritten: v1's flagged verdict survives v2's pass
    assert history[0]["verdict"] == "pending_adjudication"
    assert history[1]["verdict"] == "pass"

    # the fix demonstrably improved the failing dimension (US5 motivation)
    run1 = client.get(f"/runs/{history[0]['id']}").json()
    run2 = client.get(f"/runs/{history[1]['id']}").json()

    def ped_recall(run):
        clean = next(
            t for t in run["tier_results"] if t["tier"] == "domain_stress" and t["condition"] == "clean"
        )
        return clean["metrics"]["safety_critical"]["pedestrian"]["recall"]

    assert ped_recall(run2) > ped_recall(run1)
