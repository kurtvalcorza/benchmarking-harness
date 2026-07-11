"""Classification metrics (T015/T033): top-1 / top-5 + macro-F1 + per-class recall.

Accounting is over the EXPECTED dataset ids, not over whatever predictions
arrived: a missing prediction is scored as incorrect and the denominator stays
the registered dataset size (T038). Omitting a hard example can therefore never
raise a score. For a complete prediction set the results are unchanged.
"""

from collections import defaultdict

from engine.adapters.base import Prediction


def evaluate_classification(
    predictions: list[Prediction], annotations: dict[str, list[dict]]
) -> dict:
    # index predictions by image; a duplicate keeps the first (coverage flags it)
    by_id: dict[str, Prediction] = {}
    for p in predictions:
        by_id.setdefault(p.image_id, p)

    total = 0
    top1 = 0
    top5 = 0
    tp: dict[str, int] = defaultdict(int)
    fp: dict[str, int] = defaultdict(int)
    fn: dict[str, int] = defaultdict(int)

    for image_id, objs in annotations.items():
        if not objs:
            continue
        truth = objs[0]["label"]
        total += 1
        pred = by_id.get(image_id)
        if pred is None:
            # missing prediction: the expected item is counted, and wrong
            fn[truth] += 1
            continue
        ranked = sorted(pred.class_scores, key=pred.class_scores.get, reverse=True)
        if pred.label == truth:
            top1 += 1
            tp[truth] += 1
        else:
            fn[truth] += 1
            if pred.label is not None:
                fp[pred.label] += 1
        if truth in ranked[:5] or pred.label == truth:
            top5 += 1

    labels = set(tp) | set(fp) | set(fn)
    f1s, recalls = [], {}
    for lbl in labels:
        prec = tp[lbl] / (tp[lbl] + fp[lbl]) if (tp[lbl] + fp[lbl]) else 0.0
        rec = tp[lbl] / (tp[lbl] + fn[lbl]) if (tp[lbl] + fn[lbl]) else 0.0
        f1s.append(2 * prec * rec / (prec + rec) if (prec + rec) else 0.0)
        recalls[lbl] = round(rec, 4)
    return {
        "top1": round(top1 / total, 4) if total else 0.0,
        "top5": round(top5 / total, 4) if total else 0.0,
        "macro_f1": round(sum(f1s) / len(f1s), 4) if f1s else 0.0,
        "per_class_recall": recalls,
        "num_images": total,
    }
