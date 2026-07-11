"""Classification metrics (T015): top-1 / top-5 + macro-F1 + per-class recall."""

from collections import defaultdict

from engine.adapters.base import Prediction


def evaluate_classification(
    predictions: list[Prediction], annotations: dict[str, list[dict]]
) -> dict:
    total = 0
    top1 = 0
    top5 = 0
    tp: dict[str, int] = defaultdict(int)
    fp: dict[str, int] = defaultdict(int)
    fn: dict[str, int] = defaultdict(int)
    for pred in predictions:
        objs = annotations.get(pred.image_id, [])
        if not objs:
            continue
        truth = objs[0]["label"]
        total += 1
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
