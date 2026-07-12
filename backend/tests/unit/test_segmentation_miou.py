"""T020 [US4] — semantic mIoU scorer + mask coverage validation.

mIoU is dataset-wide per-class pixel IoU (research.md R1): intersection/union
pixels accumulated over the whole set, missing prediction = empty mask (lowers
IoU). Per-instance masks reduce to a per-class semantic mask deterministically,
cross-class overlap resolved by confidence (R4). Masks are COCO RLE (R3).

These are pure-Python (numpy + pycocotools, both CORE deps) so they run in CI —
no ml extra, no live model.
"""

import numpy as np
import pytest
from pycocotools import mask as coco_mask

from engine.adapters.base import Prediction
from engine.metrics import compute_coverage
from engine.metrics.segmentation import evaluate_segmentation

SIZE = 8


def _rle(arr: np.ndarray) -> dict:
    """COCO RLE (counts as ascii str) for a HxW binary array — encoded with the
    reference pycocotools, INDEPENDENT of the scorer's own encoder, so the test
    doubles as reference agreement (the scorer must read pycocotools masks)."""
    r = coco_mask.encode(np.asfortranarray(arr.astype(np.uint8)))
    return {"size": [int(r["size"][0]), int(r["size"][1])], "counts": r["counts"].decode("ascii")}


def _band(r0: int, r1: int) -> np.ndarray:
    """A SIZE×SIZE mask with rows [r0, r1) set."""
    m = np.zeros((SIZE, SIZE), dtype=np.uint8)
    m[r0:r1, :] = 1
    return m


def _pred(image_id, instances):
    return Prediction(image_id=image_id, masks=instances)


# --------------------------------------------------------------------------- #
# mIoU numeric identity                                                        #
# --------------------------------------------------------------------------- #


def test_perfect_prediction_scores_miou_one():
    ann = {"a": [{"label": "vehicle", "rle": _rle(_band(0, 4))}]}
    preds = [_pred("a", [{"label": "vehicle", "score": 0.9, "rle": _rle(_band(0, 4))}])]
    m = evaluate_segmentation(preds, ann)
    assert m["miou"] == 1.0
    assert m["per_class_iou"]["vehicle"] == 1.0
    assert m["num_images"] == 1


def test_partial_overlap_matches_hand_computed_iou():
    # GT rows 0..3 (32 px), pred rows 2..5 (32 px); ∩ = rows 2..3 (16), ∪ = rows 0..5 (48)
    ann = {"a": [{"label": "vehicle", "rle": _rle(_band(0, 4))}]}
    preds = [_pred("a", [{"label": "vehicle", "score": 0.8, "rle": _rle(_band(2, 6))}])]
    m = evaluate_segmentation(preds, ann)
    # scorer rounds to 4 dp (like the detection metrics)
    assert m["per_class_iou"]["vehicle"] == pytest.approx(round(16 / 48, 4), abs=1e-9)


def test_missing_prediction_lowers_iou_complete_accounting():
    # two images, one perfect, one with NO prediction (empty mask, counted)
    ann = {
        "a": [{"label": "vehicle", "rle": _rle(_band(0, 4))}],
        "b": [{"label": "vehicle", "rle": _rle(_band(0, 4))}],
    }
    preds = [_pred("a", [{"label": "vehicle", "score": 0.9, "rle": _rle(_band(0, 4))}])]
    m = evaluate_segmentation(preds, ann)
    # ∩ = image a (32), ∪ = a (32) + b's uncovered GT (32) = 64 → IoU 0.5
    assert m["per_class_iou"]["vehicle"] == pytest.approx(0.5, abs=1e-6)


def test_bbox_iou_cannot_stand_in_for_mask_iou():
    # identical bounding boxes, disjoint MASKS → mask IoU must be 0, not 1
    left = np.zeros((SIZE, SIZE), np.uint8)
    left[0:SIZE, 0:1] = 1
    right = np.zeros((SIZE, SIZE), np.uint8)
    right[0:SIZE, SIZE - 1 : SIZE] = 1
    ann = {"a": [{"label": "vehicle", "bbox": [0, 0, SIZE, SIZE], "rle": _rle(left)}]}
    preds = [
        _pred("a", [{"label": "vehicle", "score": 0.9, "bbox": [0, 0, SIZE, SIZE], "rle": _rle(right)}])
    ]
    m = evaluate_segmentation(preds, ann)
    assert m["per_class_iou"]["vehicle"] == 0.0


# --------------------------------------------------------------------------- #
# instance → semantic reduction (deterministic, confidence-priority)          #
# --------------------------------------------------------------------------- #


def test_same_class_instances_union():
    ann = {"a": [{"label": "vehicle", "rle": _rle(_band(0, 4))}]}
    # two half-masks of the same class must union to the full GT band
    preds = [
        _pred(
            "a",
            [
                {"label": "vehicle", "score": 0.9, "rle": _rle(_band(0, 2))},
                {"label": "vehicle", "score": 0.8, "rle": _rle(_band(2, 4))},
            ],
        )
    ]
    m = evaluate_segmentation(preds, ann)
    assert m["per_class_iou"]["vehicle"] == 1.0


def test_cross_class_overlap_resolved_by_confidence():
    # both instances claim the SAME pixels; the higher-confidence class owns them
    ann = {"a": [{"label": "vehicle", "rle": _rle(_band(0, 4))}]}
    preds = [
        _pred(
            "a",
            [
                {"label": "vehicle", "score": 0.95, "rle": _rle(_band(0, 4))},
                {"label": "pedestrian", "score": 0.50, "rle": _rle(_band(0, 4))},
            ],
        )
    ]
    m = evaluate_segmentation(preds, ann)
    # vehicle (higher score) wins the overlap → its mask matches GT exactly
    assert m["per_class_iou"]["vehicle"] == 1.0


def test_reduction_is_deterministic_regardless_of_instance_order():
    ann = {"a": [{"label": "vehicle", "rle": _rle(_band(0, 4))}]}
    ordered = [
        {"label": "vehicle", "score": 0.95, "rle": _rle(_band(0, 4))},
        {"label": "pedestrian", "score": 0.50, "rle": _rle(_band(0, 4))},
    ]
    m1 = evaluate_segmentation([_pred("a", list(ordered))], ann)
    m2 = evaluate_segmentation([_pred("a", list(reversed(ordered)))], ann)
    assert m1["per_class_iou"] == m2["per_class_iou"]  # order-independent (SC-004)


# --------------------------------------------------------------------------- #
# mask coverage validation (typed errors — FR-216)                            #
# --------------------------------------------------------------------------- #


def _codes(cov) -> set[str]:
    return {i["code"] for i in cov.issues}


def test_malformed_rle_is_a_typed_coverage_error():
    ann = {"a": [{"label": "vehicle", "rle": _rle(_band(0, 4))}]}
    preds = [_pred("a", [{"label": "vehicle", "score": 0.9, "rle": {"size": [8, 8], "counts": "!!!not-rle"}}])]
    cov = compute_coverage(preds, ann)
    assert "malformed_rle" in _codes(cov)
    assert cov.valid is False  # untrusted output can never pass


def test_mask_dim_mismatch_is_a_typed_coverage_error():
    ann = {"a": [{"label": "vehicle", "rle": _rle(_band(0, 4))}]}  # 8×8 image
    wrong = np.zeros((4, 4), np.uint8)
    wrong[0:2, :] = 1
    preds = [_pred("a", [{"label": "vehicle", "score": 0.9, "rle": _rle(wrong)}])]  # 4×4 mask
    cov = compute_coverage(preds, ann)
    assert "mask_dim_mismatch" in _codes(cov)
    assert cov.valid is False


def test_valid_masks_pass_coverage():
    ann = {
        "a": [{"label": "vehicle", "rle": _rle(_band(0, 4))}],
        "b": [{"label": "pedestrian", "rle": _rle(_band(4, 8))}],
    }
    preds = [
        _pred("a", [{"label": "vehicle", "score": 0.9, "rle": _rle(_band(0, 4))}]),
        _pred("b", [{"label": "pedestrian", "score": 0.9, "rle": _rle(_band(4, 8))}]),
    ]
    cov = compute_coverage(preds, ann)
    assert cov.valid is True
    assert cov.expected_count == 2 and cov.missing_count == 0


# --------------------------------------------------------------------------- #
# malformed instances never crash scoring (completed run w/ invalid coverage,  #
# not an infra failure)                                                        #
# --------------------------------------------------------------------------- #


def test_structurally_invalid_instance_does_not_crash_scoring():
    """A non-dict mask entry and a non-numeric `score` are coverage-flagged; the
    scorer must not raise (which would be recorded as an infra failure instead of
    a completed run with invalid coverage)."""
    ann = {"a": [{"label": "vehicle", "rle": _rle(_band(0, 4))}]}
    preds = [
        _pred(
            "a",
            [
                "not-a-dict",  # structurally invalid instance
                {"label": "vehicle", "score": "high", "rle": _rle(_band(0, 4))},  # bad score
            ],
        )
    ]
    m = evaluate_segmentation(preds, ann)  # must not raise
    assert "miou" in m
    cov = compute_coverage(preds, ann)
    assert cov.valid is False  # the malformed entry invalidates the run


def test_nonfinite_mask_score_is_a_typed_coverage_error():
    """A NaN/inf per-instance mask score drives the reduction ordering, so it
    must invalidate the run rather than silently steer priority (FR-216)."""
    ann = {"a": [{"label": "vehicle", "rle": _rle(_band(0, 4))}]}
    preds = [
        _pred("a", [{"label": "vehicle", "score": float("nan"), "rle": _rle(_band(0, 4))}])
    ]
    cov = compute_coverage(preds, ann)
    assert "nan_score" in _codes(cov)
    assert cov.valid is False
    evaluate_segmentation(preds, ann)  # must not raise despite the NaN score
