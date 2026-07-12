"""T022 [US4] — a segmentation submission scores mIoU end-to-end through the
registry, with NO harness change beyond the scorer/adapter seams (FR-020/025).

Uses the stub-seg adapter (deterministic masks from ground truth) so the whole
pipeline runs offline in CI: register a segmentation golden set (masks + IoU
floors), submit a segmenter, and assert Tier-1 mIoU + Tier-2 per-class IoU are
scored and the run routes correctly.
"""

from tests.conftest import (
    HEALTHY_SEG,
    det_manifest,
    register_golden,
    seg_manifest,
    submit_model,
)


def _seg_run(client):
    register_golden(client, seg_manifest())
    mv = submit_model(
        client,
        weights_path=HEALTHY_SEG,
        name="healthy-segmenter",
        model_class="segmentation",
        sources=["synthetic seg v1"],
    )
    runs = client.get(f"/models/{mv['id']}/history").json()
    run = client.get(f"/runs/{runs[-1]['id']}").json()
    return mv, run


def test_segmentation_scores_miou_via_registry(client):
    mv, run = _seg_run(client)
    # segmentation thresholds are unratified (governance ratifies the number
    # later, FR-207) → the run is routed to human adjudication, never a silent
    # pass or fail.
    assert mv["status"] == "pending_adjudication", mv
    t1 = next(t for t in run["tier_results"] if t["tier"] == "capability")
    assert t1["metrics"]["benchmark"] == "Cityscapes mIoU"  # registry-selected slot
    assert t1["metrics"]["miou"] > 0.5  # near-perfect stub masks
    assert set(t1["metrics"]["per_class_iou"]) >= {"pedestrian", "vehicle", "traffic_sign"}
    assert t1["coverage"]["valid"] is True
    assert "unratified_threshold" in (run["flag_trigger"] or "")


def test_segmentation_tier2_reports_per_class_iou_floors(client):
    _mv, run = _seg_run(client)
    t2 = [t for t in run["tier_results"] if t["tier"] == "domain_stress"]
    assert {t["condition"] for t in t2} == {"clean", "rain", "low_light", "fog"}
    clean = next(t for t in t2 if t["condition"] == "clean")
    assert "pedestrian" in clean["metrics"]["per_class_iou"]
    sc = clean["metrics"]["safety_critical"]["pedestrian"]
    # the safety-critical floor is checked against IoU for segmentation (FR-214),
    # not recall — the row is metric-typed
    assert sc["metric"] == "iou"
    assert sc["floor"] == 0.4
    assert sc["value"] is not None and isinstance(sc["ok"], bool)


def test_segmentation_run_persists_mask_evidence(client):
    """FR-218: the reduced per-class masks are content-addressed evidence the
    tier result can resolve, not a number with no backing bytes."""
    _mv, run = _seg_run(client)
    t1 = next(t for t in run["tier_results"] if t["tier"] == "capability")
    ev = t1["metrics"].get("segmentation_evidence")
    assert ev and ev.get("evidence_ref") and ev.get("evidence_digest")


# --------------------------------------------------------------------------- #
# golden-set registration: masks required + IoU floors (FR-214/FR-219)        #
# --------------------------------------------------------------------------- #


def test_detection_shaped_dataset_rejected_as_segmentation(client):
    """FR-219: a label+bbox dataset with no masks must NOT register as a
    segmentation golden set — bbox IoU can't stand in for mask IoU."""
    r = client.post(
        "/golden-sets",
        json=seg_manifest(name="fake-seg", data_ref=str(det_manifest()["data_ref"])),
    )
    assert r.status_code == 422
    assert "mask" in r.text.lower() or "rle" in r.text.lower()


def test_segmentation_missing_iou_floor_rejected(client):
    """Every safety-critical class needs a floor (FR-026, generalized to IoU)."""
    r = client.post("/golden-sets", json=seg_manifest(iou_floors={}))
    assert r.status_code == 422
    assert "pedestrian" in r.text


def test_segmentation_registration_stores_iou_floors(client):
    out = register_golden(client, seg_manifest())
    assert out["recall_floors"].get("pedestrian") == 0.4  # stored generic floor
    assert out["model_class"] == "segmentation"
    # the floor is IoU-typed, surfaced so a consumer need not infer from model_class
    assert out["floor_metric"] == "iou"
