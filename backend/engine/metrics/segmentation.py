"""Segmentation metrics (US4): semantic mean IoU via the pinned pycocotools RLE.

Tier-1 capability = **semantic mIoU** (research.md R1): for each registered
class, intersection and union PIXEL counts are accumulated over the whole
dataset, per-class IoU = ∩ / ∪, and `miou` = mean over classes. Dataset-level
pixel accumulation (not mean of per-image IoU) is the Cityscapes/PASCAL
convention and is stable on small sets. The denominator is the registered
dataset: a missing prediction is an empty mask (counted, lowers IoU) — the US2
complete-accounting rule.

Masks are COCO RLE (`pycocotools.mask`, a CORE dep — R3): compact, lossless at
the pixel level, and deterministic as bytes so mask evidence is content-
addressed and reproducible (SC-004). The `-seg` adapter emits PER-INSTANCE
masks; the scorer reduces them to one per-class semantic mask per image
deterministically — sort by (score desc, index asc), first (highest-confidence)
claimant owns each pixel, same-class instances union (R4).

pycocotools is dependency-light (C/NumPy), so this scorer runs in CI and tests
without the heavy `ml` runtime.
"""

from collections import defaultdict

import numpy as np

from engine.adapters.base import Prediction


def _counts_to_bytes(rle: dict) -> dict:
    """pycocotools decodes RLE whose `counts` is bytes; our on-the-wire form
    stores it as an ascii str (plain JSON), so normalize here."""
    counts = rle["counts"]
    return {
        "size": [int(rle["size"][0]), int(rle["size"][1])],
        "counts": counts.encode("ascii") if isinstance(counts, str) else counts,
    }


def rle_encode(mask: np.ndarray) -> dict:
    """COCO RLE for a HxW binary array; `counts` returned as an ascii str."""
    from pycocotools import mask as coco_mask

    r = coco_mask.encode(np.asfortranarray(mask.astype(np.uint8)))
    counts = r["counts"]
    return {
        "size": [int(r["size"][0]), int(r["size"][1])],
        "counts": counts.decode("ascii") if isinstance(counts, bytes) else counts,
    }


def rle_decode(rle: dict) -> np.ndarray:
    """Decode a COCO RLE (ascii-str or bytes `counts`) to a HxW uint8 mask."""
    from pycocotools import mask as coco_mask

    return coco_mask.decode(_counts_to_bytes(rle))


def mask_size(rle: dict) -> tuple[int, int] | None:
    """(H, W) declared by an RLE payload, or None if it is not a valid size."""
    size = rle.get("size") if isinstance(rle, dict) else None
    if isinstance(size, (list, tuple)) and len(size) == 2:
        try:
            h, w = int(size[0]), int(size[1])
        except (TypeError, ValueError):
            return None
        if h > 0 and w > 0:
            return h, w
    return None


def _image_size(gt_objs: list[dict], pred_instances: list[dict]) -> tuple[int, int] | None:
    """Resolve an image's (H, W) from ground-truth masks first, then predictions."""
    for obj in gt_objs:
        s = mask_size(obj.get("rle")) if isinstance(obj.get("rle"), dict) else None
        if s:
            return s
    for inst in pred_instances:
        s = mask_size(inst.get("rle")) if isinstance(inst.get("rle"), dict) else None
        if s:
            return s
    return None


def _safe_decode(rle: dict, size: tuple[int, int]) -> np.ndarray | None:
    """Decode a mask to the image size, or None if it is malformed / mismatched
    (coverage records the typed error separately — the scorer just skips it so a
    bad payload can never crash a run)."""
    if not isinstance(rle, dict) or mask_size(rle) != size:
        return None
    try:
        m = rle_decode(rle)
    except Exception:  # noqa: BLE001 — malformed RLE is flagged by coverage, not here
        return None
    if m.shape != size:
        return None
    return m.astype(bool)


def reduce_instances_to_semantic(
    instances: list[dict], size: tuple[int, int]
) -> dict[str, np.ndarray]:
    """Reduce per-instance masks to one per-class semantic boolean mask (R4).

    Deterministic: sort by (score desc, original index asc); paint into a single
    ownership map so the first (highest-confidence) instance claims each pixel
    (cross-class overlap → higher score wins); same-class instances union.
    Order-independent for identical inputs (SC-004).
    """
    order = sorted(
        range(len(instances)),
        key=lambda i: (-float(instances[i].get("score", 0.0)), i),
    )
    claimed = np.zeros(size, dtype=bool)
    per_class: dict[str, np.ndarray] = {}
    for i in order:
        inst = instances[i]
        m = _safe_decode(inst.get("rle"), size)
        if m is None:
            continue
        fresh = m & ~claimed  # only pixels not already owned by a higher-conf instance
        if not fresh.any():
            continue
        label = inst.get("label")
        if label not in per_class:
            per_class[label] = np.zeros(size, dtype=bool)
        per_class[label] |= fresh
        claimed |= m
    return per_class


def _reduce_gt_to_semantic(gt_objs: list[dict], size: tuple[int, int]) -> dict[str, np.ndarray]:
    """Ground truth carries no confidence: union all instance masks per class."""
    per_class: dict[str, np.ndarray] = {}
    for obj in gt_objs:
        m = _safe_decode(obj.get("rle"), size)
        if m is None:
            continue
        label = obj["label"]
        if label not in per_class:
            per_class[label] = np.zeros(size, dtype=bool)
        per_class[label] |= m
    return per_class


def evaluate_segmentation(
    predictions: list[Prediction], annotations: dict[str, list[dict]]
) -> dict:
    """Semantic mIoU + per-class IoU over the registered dataset.

    `reduced_masks` (per image → per class RLE) is returned so the orchestrator
    can persist it as content-addressed mask evidence (FR-218); the tier moves it
    out of the metrics column before persistence.
    """
    by_id: dict[str, Prediction] = {}
    for p in predictions:
        by_id.setdefault(p.image_id, p)  # duplicate keeps the first (coverage flags it)

    # registered classes = every class that appears in ground-truth masks
    classes = {
        obj["label"]
        for objs in annotations.values()
        for obj in objs
        if isinstance(obj.get("rle"), dict)
    }

    inter: dict[str, int] = defaultdict(int)
    union: dict[str, int] = defaultdict(int)
    num_predictions = 0
    reduced_masks: dict[str, dict[str, dict]] = {}

    for image_id, objs in annotations.items():
        pred = by_id.get(image_id)
        pred_instances = list(pred.masks) if pred else []
        num_predictions += len(pred_instances)
        size = _image_size(objs, pred_instances)
        if size is None:
            continue  # no mask evidence for this image at all → nothing to score
        gt_sem = _reduce_gt_to_semantic(objs, size)
        pred_sem = reduce_instances_to_semantic(pred_instances, size)
        if pred_sem:
            reduced_masks[image_id] = {
                label: rle_encode(mask) for label, mask in pred_sem.items()
            }
        empty = np.zeros(size, dtype=bool)
        for cls in classes:
            g = gt_sem.get(cls, empty)
            p_mask = pred_sem.get(cls, empty)
            inter[cls] += int(np.logical_and(g, p_mask).sum())
            union[cls] += int(np.logical_or(g, p_mask).sum())

    per_class_iou = {
        cls: round(inter[cls] / union[cls], 4) for cls in sorted(classes) if union[cls] > 0
    }
    miou = round(sum(per_class_iou.values()) / len(per_class_iou), 4) if per_class_iou else 0.0
    return {
        "miou": miou,
        "per_class_iou": per_class_iou,
        "num_images": len(annotations),
        "num_predictions": num_predictions,
        # popped into tier evidence + content-addressed by the orchestrator
        # (never persisted raw in the metrics column) — FR-218
        "reduced_masks": reduced_masks,
    }
