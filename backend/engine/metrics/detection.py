"""Detection metrics (T034/T035, US2): COCO Average Precision via the pinned
``pycocotools`` reference evaluator.

The COCO-named metrics (`coco_ap_50_95`, `coco_ap_50`) come from
`pycocotools.cocoeval.COCOeval` — the reference implementation — never a
home-grown approximation (metric-evidence.md §Metric identity). `map_50_95` is
retained ONLY as an alias that is *numerically identical* to `coco_ap_50_95`
for API/card back-compat. The previous single-point precision×recall
approximation survives under the honest `diagnostic_precision_recall_product`
name and MUST NOT be bound to a ratified COCO threshold.

Per-class recall (IoU 0.5, greedy matching) is retained for the Tier 2
safety-critical gate: its definition is stable and independent of the AP
ranking, so it never changes the meaning of a recall floor.

pycocotools is a core dependency (dependency-light C/NumPy, not the heavy `ml`
runtime), so the reference evaluator is available in CI and tests. When it is
somehow absent the detection metrics fall back to the diagnostic approximation
under its honest name and the COCO keys are omitted — a run then cannot satisfy
the ratified `coco_ap_50_95` threshold and lands in adjudication (fail-closed).
"""

import contextlib
import io
from collections import defaultdict

from engine.adapters.base import Prediction

# COCO-standard reference configuration (metric-evidence.md evidence example).
IOU_THRESHOLDS = [round(0.5 + 0.05 * i, 2) for i in range(10)]
MAX_DETECTIONS = [1, 10, 100]


def _iou(a: list[float], b: list[float]) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _match_counts(
    predictions: list[Prediction],
    annotations: dict[str, list[dict]],
    iou_thr: float,
) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    """Greedy per-image matching → (tp, fp, gt_count) per class label."""
    tp: dict[str, int] = defaultdict(int)
    fp: dict[str, int] = defaultdict(int)
    gt_n: dict[str, int] = defaultdict(int)
    for objs in annotations.values():
        for obj in objs:
            if "bbox" in obj:
                gt_n[obj["label"]] += 1
    for pred in predictions:
        gt = [o for o in annotations.get(pred.image_id, []) if "bbox" in o]
        used = [False] * len(gt)
        order = sorted(range(len(pred.boxes)), key=lambda i: -pred.scores[i])
        for i in order:
            box, label = pred.boxes[i], pred.labels[i]
            best_j, best_iou = -1, iou_thr
            for j, obj in enumerate(gt):
                if used[j] or obj["label"] != label:
                    continue
                iou = _iou(box, obj["bbox"])
                if iou >= best_iou:
                    best_j, best_iou = j, iou
            if best_j >= 0:
                used[best_j] = True
                tp[label] += 1
            else:
                fp[label] += 1
    return tp, fp, gt_n


def _per_class_recall_at_50(
    predictions: list[Prediction], annotations: dict[str, list[dict]]
) -> dict[str, float]:
    """Per-class recall at IoU 0.5 (greedy) — the Tier 2 safety-critical gate."""
    tp, _fp, gt_n = _match_counts(predictions, annotations, 0.5)
    return {label: round(tp[label] / n, 4) for label, n in gt_n.items() if n > 0}


def _diagnostic_precision_recall_product(
    predictions: list[Prediction], annotations: dict[str, list[dict]]
) -> float:
    """The retained lightweight approximation (single-point precision×recall,
    averaged over IoU thresholds), renamed honestly per metric-evidence.md. A
    fast dependency-free cross-check, NEVER a COCO metric and never a gate."""
    per_thr_ap = []
    for thr in IOU_THRESHOLDS:
        tp, fp, gt_n = _match_counts(predictions, annotations, thr)
        aps = []
        for label, n in gt_n.items():
            if n == 0:
                continue
            recall = tp[label] / n
            precision = (
                tp[label] / (tp[label] + fp[label]) if (tp[label] + fp[label]) > 0 else 0.0
            )
            aps.append(precision * recall)
        per_thr_ap.append(sum(aps) / len(aps) if aps else 0.0)
    return round(sum(per_thr_ap) / len(per_thr_ap), 4) if per_thr_ap else 0.0


def _xywh(box: list[float]) -> list[float]:
    x1, y1, x2, y2 = box
    return [x1, y1, x2 - x1, y2 - y1]


def _coco_ap(
    predictions: list[Prediction], annotations: dict[str, list[dict]]
) -> tuple[float, float] | None:
    """(coco_ap_50_95, coco_ap_50) from the pinned pycocotools reference, or
    None when pycocotools is unavailable (→ COCO keys omitted, fail-closed)."""
    try:
        from pycocotools.coco import COCO
        from pycocotools.cocoeval import COCOeval
    except ImportError:
        return None

    labels = {o["label"] for objs in annotations.values() for o in objs if "bbox" in o}
    labels |= {lbl for p in predictions for lbl in p.labels}
    image_ids = set(annotations) | {p.image_id for p in predictions}
    if not labels or not image_ids:
        return 0.0, 0.0
    cat_of = {name: i + 1 for i, name in enumerate(sorted(labels))}
    img_of = {name: i + 1 for i, name in enumerate(sorted(image_ids))}

    gt_annotations = []
    aid = 1
    for image_id, objs in annotations.items():
        for obj in objs:
            if "bbox" not in obj:
                continue
            x1, y1, x2, y2 = obj["bbox"]
            gt_annotations.append(
                {
                    "id": aid,
                    "image_id": img_of[image_id],
                    "category_id": cat_of[obj["label"]],
                    "bbox": _xywh(obj["bbox"]),
                    "area": max(0.0, (x2 - x1) * (y2 - y1)),
                    "iscrowd": 0,
                }
            )
            aid += 1
    results = []
    for p in predictions:
        for box, score, label in zip(p.boxes, p.scores, p.labels, strict=False):
            results.append(
                {
                    "image_id": img_of[p.image_id],
                    "category_id": cat_of[label],
                    "bbox": _xywh(box),
                    "score": float(score),
                }
            )
    # no ground truth or no detections → COCOeval AP is undefined/degenerate;
    # both cases are an honest zero, not a spurious -1
    if not gt_annotations or not results:
        return 0.0, 0.0

    dataset = {
        "images": [{"id": img_of[k]} for k in sorted(image_ids)],
        "categories": [{"id": cid, "name": name} for name, cid in cat_of.items()],
        "annotations": gt_annotations,
    }
    with contextlib.redirect_stdout(io.StringIO()):
        coco_gt = COCO()
        coco_gt.dataset = dataset
        coco_gt.createIndex()
        coco_dt = coco_gt.loadRes(results)
        ev = COCOeval(coco_gt, coco_dt, iouType="bbox")
        ev.params.maxDets = list(MAX_DETECTIONS)
        ev.evaluate()
        ev.accumulate()
        ev.summarize()
    return round(float(ev.stats[0]), 4), round(float(ev.stats[1]), 4)


def evaluate_detection(
    predictions: list[Prediction], annotations: dict[str, list[dict]]
) -> dict:
    """Returns COCO AP (`coco_ap_50_95`, `coco_ap_50`, `map_50_95` alias),
    per-class recall (IoU 0.5, safety gate) and the renamed diagnostic."""
    out: dict = {
        "per_class_recall": _per_class_recall_at_50(predictions, annotations),
        "diagnostic_precision_recall_product": _diagnostic_precision_recall_product(
            predictions, annotations
        ),
        "num_images": len(annotations),
        "num_predictions": sum(len(p.boxes) for p in predictions),
    }
    coco = _coco_ap(predictions, annotations)
    if coco is not None:
        ap_50_95, ap_50 = coco
        out["coco_ap_50_95"] = ap_50_95
        out["coco_ap_50"] = ap_50
        # metric-evidence.md: the legacy name is permitted ONLY as an alias
        # numerically identical to the reference metric
        out["map_50_95"] = ap_50_95
        out["map_50"] = ap_50
    return out
