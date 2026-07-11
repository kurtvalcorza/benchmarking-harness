"""Detection metrics (T015): simplified mAP + per-class recall.

Greedy IoU matching at multiple thresholds (0.5:0.95 in 0.05 steps), averaged —
a faithful, dependency-light COCO-style stand-in for the POC. When the `ml`
extra is installed, pycocotools can replace this for real benchmarks; the
metric KEYS (map_50_95, per_class_recall) are the contract, not the backend.
"""

from collections import defaultdict

from engine.adapters.base import Prediction

IOU_THRESHOLDS = [0.5 + 0.05 * i for i in range(10)]


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


def evaluate_detection(
    predictions: list[Prediction], annotations: dict[str, list[dict]]
) -> dict:
    """Returns {map_50_95, map_50, per_class_recall (at IoU 0.5), ...}."""
    per_thr_ap = []
    recall_50: dict[str, float] = {}
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
            # single-point AP approximation (precision × recall) for the POC
            aps.append(precision * recall)
            if thr == 0.5:
                recall_50[label] = round(recall, 4)
        per_thr_ap.append(sum(aps) / len(aps) if aps else 0.0)
    return {
        "map_50_95": round(sum(per_thr_ap) / len(per_thr_ap), 4),
        "map_50": round(per_thr_ap[0], 4),
        "per_class_recall": recall_50,
        "num_images": len(annotations),
        "num_predictions": sum(len(p.boxes) for p in predictions),
    }
