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


def test_missing_data_ref_rejected(client):
    """A set the worker can't read would infra-fail every run for the class."""
    r = client.post("/golden-sets", json=det_manifest(data_ref="", checksum="whatever"))
    assert r.status_code == 422
    assert "data_ref" in r.text


def test_checksum_mismatch_rejected(client):
    r = client.post("/golden-sets", json=det_manifest(checksum="not-the-real-hash"))
    assert r.status_code == 422
    assert "contamination" in r.text


def test_malformed_dataset_rejected_at_registration(client, tmp_path):
    """Broken annotations must be caught at registration, not crash Tier 2."""
    bad = tmp_path / "bad-golden"
    (bad / "images").mkdir(parents=True)
    (bad / "annotations.json").write_text("{not json")
    r = client.post("/golden-sets", json=det_manifest(data_ref=str(bad)))
    assert r.status_code == 422
    assert "not valid JSON" in r.text

    (bad / "annotations.json").write_text('{"img_000": [{"bbox": [1, 2, 3, 4]}]}')
    r = client.post("/golden-sets", json=det_manifest(data_ref=str(bad)))
    assert r.status_code == 422  # missing label + no images


def test_checksum_drift_blocks_evaluation(client, tmp_path):
    """Data mutated after registration must never be scored under the old
    checksum (FR-018) — the run records an infra failure instead."""
    import shutil

    from tests.conftest import DET_GOLDEN, HEALTHY_DET

    drifting = tmp_path / "drifting-golden"
    shutil.copytree(DET_GOLDEN, drifting)
    register_golden(client, det_manifest(data_ref=str(drifting)))
    # mutate the registered data on disk
    victim = next((drifting / "images").glob("*.png"))
    victim.write_bytes(victim.read_bytes() + b"tampered")

    mv = submit_model(client, weights_path=HEALTHY_DET, name="drift-victim", sources=["s"])
    assert mv["status"] == "pending"  # infra failure, not a model verdict
    runs = client.get(f"/models/{mv['id']}/history").json()
    assert runs[-1]["infra_ok"] is False
    assert "checksum" in runs[-1]["flag_trigger"]


def test_pending_adjudication_reevaluated_on_golden_set_update(client):
    """FR-004: a case still awaiting adjudication re-evaluates against the new
    set so the reviewer never decides on stale evidence."""
    from tests.conftest import WEAK_DET

    register_golden(client, det_manifest())
    mv = submit_model(client, weights_path=WEAK_DET, name="stale-flagged", sources=["s"])
    assert mv["status"] == "pending_adjudication"
    out = register_golden(client, det_manifest(version="v2"))
    assert mv["id"] in out["reevaluation_flagged"]
    history = client.get(f"/models/{mv['id']}/history").json()
    assert len(history) == 2
    assert history[1]["golden_set"]["version"] == "v2"
    # still weak → flagged again, but now against current evidence
    assert client.get(f"/models/{mv['id']}").json()["status"] == "pending_adjudication"


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
