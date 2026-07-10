"""T061 — Scenario D: same model + same golden set → same verdict and scores
(SC-004, Constitution IV)."""

from tests.conftest import HEALTHY_DET, det_manifest, register_golden, submit_model


def test_rerun_reproduces_verdict_and_scores(client):
    register_golden(client, det_manifest())
    # two versions carrying the SAME weights → two independent runs of the suite
    a = submit_model(client, weights_path=HEALTHY_DET, name="repro", version="v1", sources=["s"])
    b = submit_model(client, weights_path=HEALTHY_DET, name="repro", version="v2", sources=["s"])
    assert a["status"] == b["status"] == "approved"

    history = client.get(f"/models/{b['id']}/history").json()
    run_a = client.get(f"/runs/{history[0]['id']}").json()
    run_b = client.get(f"/runs/{history[1]['id']}").json()
    assert run_a["verdict"] == run_b["verdict"]

    def scores(run):
        return {
            (t["tier"], t["condition"]): {
                k: v
                for k, v in t["metrics"].items()
                # timing-derived numbers legitimately vary run to run
                if k not in ("latency_ms_per_image", "throughput_images_per_s")
            }
            for t in run["tier_results"]
        }

    assert scores(run_a) == scores(run_b)  # exact — within any tolerance

    # both runs stamped with the same golden-set checksum (FR-018)
    assert run_a["golden_set"]["checksum"] == run_b["golden_set"]["checksum"]
