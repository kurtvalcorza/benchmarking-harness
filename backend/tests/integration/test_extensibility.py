"""T056 — Scenario E: register a classification golden set + evaluate a
classifier via the registry with NO harness change (FR-020/025, US6).
Plus golden-set manifest validation and the FR-004 re-eval trigger (T059)."""

from tests.conftest import (
    HEALTHY_CLS,
    HEALTHY_DET,
    cls_manifest,
    det_manifest,
    register_golden,
    submit_model,
)


def test_classifier_evaluates_via_registry(client):
    register_golden(client, cls_manifest())
    mv = submit_model(
        client,
        weights_path=HEALTHY_CLS,
        name="healthy-classifier",
        model_class="classification",
        sources=["synthetic v1"],
    )
    assert mv["status"] == "approved", mv
    runs = client.get(f"/models/{mv['id']}/history").json()
    run = client.get(f"/runs/{runs[0]['id']}").json()
    t1 = next(t for t in run["tier_results"] if t["tier"] == "capability")
    assert t1["metrics"]["benchmark"] == "ImageNet top-1"  # registry-selected slot
    assert t1["metrics"]["top1"] >= 0.6


def test_is_public_true_rejected(client):
    r = client.post("/golden-sets", json=det_manifest(is_public=True))
    assert r.status_code == 422


def test_missing_recall_floor_rejected(client):
    r = client.post("/golden-sets", json=det_manifest(recall_floors={}))
    assert r.status_code == 422
    assert "pedestrian" in r.text


def test_restrictive_license_rejected(client):
    r = client.post("/golden-sets", json=det_manifest(license="cc-by-nc-4.0"))
    assert r.status_code == 422


def test_checksum_mismatch_rejected(client):
    r = client.post("/golden-sets", json=det_manifest(checksum="not-the-real-hash"))
    assert r.status_code == 422
    assert "contamination" in r.text


def test_golden_set_update_flags_reevaluation(client):
    """FR-004: models evaluated against v1 are re-flagged when v2 registers."""
    register_golden(client, det_manifest())
    mv = submit_model(client, weights_path=HEALTHY_DET, name="reeval-me", sources=["s"])
    assert mv["status"] == "approved"
    out = register_golden(client, det_manifest(version="v2"))
    assert mv["id"] in out["reevaluation_flagged"]
    # inline mode: the re-run already happened, against the NEW set version
    history = client.get(f"/models/{mv['id']}/history").json()
    assert len(history) == 2
    assert history[1]["golden_set"]["version"] == "v2"
