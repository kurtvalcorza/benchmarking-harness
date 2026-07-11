"""T031 [US2] — the detection evaluator's COCO-named metrics come from the
pinned pycocotools reference implementation, not a home-grown approximation
(metric-evidence.md §Metric identity).

These are deterministic direct-reference comparisons: the same predictions and
annotations are scored independently through a fresh ``pycocotools.COCOeval`` in
the test and the results MUST match ``evaluate_detection`` exactly. The old
single-point precision×recall approximation may only survive under the honest
``diagnostic_precision_recall_product`` name and MUST NOT be bound to the
ratified COCO threshold.
"""

import contextlib
import io

import pytest

from app.db.enums import ModelClass, Tier
from app.services.config import get_threshold
from engine.adapters.base import Prediction

pytest.importorskip("pycocotools")

from engine.metrics.detection import (  # noqa: E402
    IOU_THRESHOLDS,
    MAX_DETECTIONS,
    evaluate_detection,
)


def _xywh(x1, y1, x2, y2):
    return [x1, y1, x2 - x1, y2 - y1]


def _reference_coco_ap(predictions, annotations):
    """Independent pycocotools invocation — the reference the impl must match."""
    from pycocotools.coco import COCO
    from pycocotools.cocoeval import COCOeval

    labels = {o["label"] for objs in annotations.values() for o in objs if "bbox" in o}
    labels |= {lbl for p in predictions for lbl in p.labels}
    image_ids = set(annotations) | {p.image_id for p in predictions}
    cat_of = {name: i + 1 for i, name in enumerate(sorted(labels))}
    img_of = {name: i + 1 for i, name in enumerate(sorted(image_ids))}

    gt = {
        "images": [{"id": img_of[k]} for k in sorted(image_ids)],
        "categories": [{"id": cid, "name": name} for name, cid in cat_of.items()],
        "annotations": [],
    }
    aid = 1
    for image_id, objs in annotations.items():
        for o in objs:
            if "bbox" not in o:
                continue
            x1, y1, x2, y2 = o["bbox"]
            gt["annotations"].append(
                {
                    "id": aid,
                    "image_id": img_of[image_id],
                    "category_id": cat_of[o["label"]],
                    "bbox": _xywh(x1, y1, x2, y2),
                    "area": max(0.0, (x2 - x1) * (y2 - y1)),
                    "iscrowd": 0,
                }
            )
            aid += 1
    results = []
    for p in predictions:
        for box, score, label in zip(p.boxes, p.scores, p.labels, strict=False):
            x1, y1, x2, y2 = box
            results.append(
                {
                    "image_id": img_of[p.image_id],
                    "category_id": cat_of[label],
                    "bbox": _xywh(x1, y1, x2, y2),
                    "score": float(score),
                }
            )
    with contextlib.redirect_stdout(io.StringIO()):
        coco_gt = COCO()
        coco_gt.dataset = gt
        coco_gt.createIndex()
        if not results or not gt["annotations"]:
            return 0.0, 0.0
        coco_dt = coco_gt.loadRes(results)
        ev = COCOeval(coco_gt, coco_dt, iouType="bbox")
        ev.evaluate()
        ev.accumulate()
        ev.summarize()
    return round(float(ev.stats[0]), 4), round(float(ev.stats[1]), 4)


def _grid_predictions(n, hit):
    """n images, one GT box each; the first `hit` are detected perfectly."""
    annotations = {f"img_{i:03d}": [{"label": "car", "bbox": [0, 0, 10, 10]}] for i in range(n)}
    preds = []
    for i in range(n):
        iid = f"img_{i:03d}"
        if i < hit:
            preds.append(Prediction(image_id=iid, boxes=[[0, 0, 10, 10]], scores=[0.9], labels=["car"]))
        else:
            preds.append(Prediction(image_id=iid, boxes=[], scores=[], labels=[]))
    return preds, annotations


def test_reserved_coco_metric_names_present():
    preds, ann = _grid_predictions(4, 4)
    m = evaluate_detection(preds, ann)
    assert "coco_ap_50_95" in m and "coco_ap_50" in m


def test_matches_direct_pycocotools_reference():
    preds, ann = _grid_predictions(10, 6)
    m = evaluate_detection(preds, ann)
    ref_ap, ref_ap50 = _reference_coco_ap(preds, ann)
    assert m["coco_ap_50_95"] == ref_ap
    assert m["coco_ap_50"] == ref_ap50


def test_perfect_detections_score_one():
    preds, ann = _grid_predictions(5, 5)
    m = evaluate_detection(preds, ann)
    assert m["coco_ap_50_95"] == pytest.approx(1.0, abs=1e-6)
    assert m["coco_ap_50"] == pytest.approx(1.0, abs=1e-6)


def test_no_predictions_scores_zero():
    preds, ann = _grid_predictions(5, 0)
    m = evaluate_detection(preds, ann)
    assert m["coco_ap_50_95"] == 0.0
    assert m["coco_ap_50"] == 0.0


def test_wrong_label_scores_zero():
    ann = {"img_000": [{"label": "pedestrian", "bbox": [0, 0, 10, 10]}]}
    preds = [Prediction(image_id="img_000", boxes=[[0, 0, 10, 10]], scores=[0.9], labels=["person"])]
    m = evaluate_detection(preds, ann)
    assert m["coco_ap_50_95"] == 0.0


def test_map_50_95_is_coco_identical_alias():
    """`map_50_95` may be retained ONLY as an alias numerically identical to the
    reference `coco_ap_50_95` (metric-evidence.md §Metric identity)."""
    preds, ann = _grid_predictions(8, 5)
    m = evaluate_detection(preds, ann)
    assert m["map_50_95"] == m["coco_ap_50_95"]


def test_diagnostic_metric_renamed_and_not_the_reference():
    preds, ann = _grid_predictions(8, 5)
    m = evaluate_detection(preds, ann)
    # the old single-point approximation survives ONLY under the honest name
    assert "diagnostic_precision_recall_product" in m
    # and the ratified detection threshold does NOT bind to it
    thr = get_threshold(ModelClass.detection, Tier.capability)
    assert thr is not None and thr.metric == "coco_ap_50_95"
    assert thr.metric != "diagnostic_precision_recall_product"


def test_reference_configuration_is_pinned_and_standard():
    assert IOU_THRESHOLDS == [round(0.5 + 0.05 * i, 2) for i in range(10)]
    assert MAX_DETECTIONS == [1, 10, 100]


def test_per_class_recall_preserved_for_safety_gate():
    preds, ann = _grid_predictions(10, 7)
    m = evaluate_detection(preds, ann)
    assert "per_class_recall" in m
    assert m["per_class_recall"]["car"] == pytest.approx(0.7, abs=1e-6)
