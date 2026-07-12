"""Prediction coverage + shape validation (T032, US2).

The core anti-inflation guarantee (FR / T038): every expected dataset item is
accounted for, so omitting or duplicating predictions can never *improve* a
score. Coverage is computed BEFORE metrics and recorded alongside them as
evidence.

Typed issue codes (bounded examples, never the raw predictions):
- ``missing_prediction``     an expected image has no prediction
- ``duplicate_prediction``   the same image is predicted more than once
- ``unexpected_prediction``  a prediction references an unknown image
- ``nan_score``              a non-finite score/probability
- ``malformed_output``       structurally invalid prediction (e.g. bad boxes)
- ``malformed_rle``          a segmentation mask whose RLE does not decode
- ``mask_dim_mismatch``      a mask sized differently from the dataset image
- ``mask_out_of_range``      a decoded mask area is negative or exceeds H×W
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

from engine.adapters.base import Prediction

MAX_ISSUE_EXAMPLES = 20  # bound the evidence; never dump the full prediction set


@dataclass
class Coverage:
    expected_count: int
    received_count: int
    scored_count: int
    missing_count: int
    duplicate_count: int
    unexpected_count: int
    valid: bool
    issues: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _add_issue(issues: list[dict], code: str, image_id: str) -> None:
    if len(issues) < MAX_ISSUE_EXAMPLES:
        issues.append({"code": code, "image_id": image_id})


def _finite(x) -> bool:
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def score_issues(predictions: list[Prediction]) -> list[dict]:
    """Non-finite (NaN/inf) scores or class probabilities → typed issues.

    Covers detection `scores`, classification `class_scores`, and segmentation
    per-instance mask `score` (which drives the reduction ordering, so a NaN
    there must invalidate the run, not silently steer priority)."""
    issues: list[dict] = []
    for p in predictions:
        mask_scores = [
            inst["score"]
            for inst in (getattr(p, "masks", None) or [])
            if isinstance(inst, dict) and "score" in inst
        ]
        bad = (
            any(not _finite(s) for s in p.scores)
            or any(not _finite(v) for v in p.class_scores.values())
            or any(not _finite(s) for s in mask_scores)
        )
        if bad:
            _add_issue(issues, "nan_score", p.image_id)
    return issues


def shape_issues(predictions: list[Prediction]) -> list[dict]:
    """Structurally invalid DETECTION output → typed `malformed_output` issues.

    A detection prediction must have matching boxes/scores/labels lengths and
    every box must be a finite 4-tuple with x2>=x1, y2>=y1. Catching this here
    (before metric calculation) yields a typed invalid-output result instead of
    an indexing crash recorded as a generic infra failure.
    """
    issues: list[dict] = []
    for p in predictions:
        if not (p.boxes or p.scores or p.labels):
            continue  # not a detection-shaped prediction
        malformed = not (len(p.boxes) == len(p.scores) == len(p.labels))
        for box in p.boxes:
            if len(box) != 4 or any(not _finite(v) for v in box):
                malformed = True
                break
            x1, y1, x2, y2 = box
            if x2 < x1 or y2 < y1:
                malformed = True
                break
        if malformed:
            _add_issue(issues, "malformed_output", p.image_id)
    return issues


_MASK_ISSUE_CODES = ("malformed_rle", "mask_dim_mismatch", "mask_out_of_range")


def _expected_dims(annotations: dict[str, list[dict]]) -> dict[str, tuple[int, int]]:
    """(H, W) per image taken from the ground-truth mask, for the dim check."""
    dims: dict[str, tuple[int, int]] = {}
    for image_id, objs in annotations.items():
        for obj in objs:
            rle = obj.get("rle") if isinstance(obj, dict) else None
            size = rle.get("size") if isinstance(rle, dict) else None
            if isinstance(size, (list, tuple)) and len(size) == 2:
                try:
                    dims[image_id] = (int(size[0]), int(size[1]))
                    break
                except (TypeError, ValueError):
                    continue
    return dims


def _validate_mask(rle, expected: tuple[int, int] | None) -> str | None:
    """Typed error code for a malformed/mismatched mask payload, or None (FR-216).

    A malformed mask is NEVER a silent empty score or a scorer crash: decode
    failures and nonsense areas surface as typed coverage errors instead.
    """
    if not isinstance(rle, dict):
        return "malformed_rle"
    size = rle.get("size")
    counts = rle.get("counts")
    if not (isinstance(size, (list, tuple)) and len(size) == 2):
        return "malformed_rle"
    try:
        h, w = int(size[0]), int(size[1])
    except (TypeError, ValueError):
        return "malformed_rle"
    if h <= 0 or w <= 0 or not isinstance(counts, (str, bytes)) or not counts:
        # empty counts is never a valid RLE (matches golden-set registration)
        return "malformed_rle"
    try:
        from pycocotools import mask as coco_mask

        counts_b = counts.encode("ascii") if isinstance(counts, str) else counts
        decoded = coco_mask.decode({"size": [h, w], "counts": counts_b})
    except Exception:  # noqa: BLE001 — any decode failure is a malformed mask
        return "malformed_rle"
    if getattr(decoded, "shape", None) != (h, w):
        return "malformed_rle"
    if expected is not None and (h, w) != expected:
        return "mask_dim_mismatch"
    area = int(decoded.sum())
    if area < 0 or area > h * w:
        return "mask_out_of_range"
    return None


def mask_issues(predictions: list[Prediction], annotations: dict[str, list[dict]]) -> list[dict]:
    """Typed issues for structurally invalid SEGMENTATION mask payloads (FR-216).

    Each predicted instance mask is validated (RLE decodes, size matches the
    dataset image dimensions, area within bounds). One issue per prediction is
    enough evidence; masks are only present on segmentation predictions."""
    dims = _expected_dims(annotations)
    issues: list[dict] = []
    for p in predictions:
        for inst in getattr(p, "masks", None) or []:
            rle = inst.get("rle") if isinstance(inst, dict) else None
            code = _validate_mask(rle, dims.get(p.image_id))
            if code:
                _add_issue(issues, code, p.image_id)
                break  # one masked-prediction issue is sufficient evidence
    return issues


def compute_coverage(predictions: list[Prediction], annotations: dict[str, list[dict]]) -> Coverage:
    """Coverage of `predictions` against the registered dataset's image ids.

    `expected_count` is the dataset denominator (annotated images), independent
    of how many predictions arrived — so a missing prediction lowers, never
    raises, downstream metrics.
    """
    expected_ids = set(annotations.keys())
    issues: list[dict] = []

    seen: dict[str, int] = {}
    for p in predictions:
        seen[p.image_id] = seen.get(p.image_id, 0) + 1

    duplicate_count = 0
    unexpected_count = 0
    for image_id, n in seen.items():
        if n > 1:
            duplicate_count += n - 1
            _add_issue(issues, "duplicate_prediction", image_id)
        if image_id not in expected_ids:
            unexpected_count += 1
            _add_issue(issues, "unexpected_prediction", image_id)

    predicted_expected = {p.image_id for p in predictions if p.image_id in expected_ids}
    missing = expected_ids - predicted_expected
    for image_id in sorted(missing):
        _add_issue(issues, "missing_prediction", image_id)

    issues.extend(score_issues(predictions))
    issues.extend(shape_issues(predictions))
    issues.extend(mask_issues(predictions, annotations))

    valid = duplicate_count == 0 and unexpected_count == 0 and not any(
        i["code"] in ("nan_score", "malformed_output", *_MASK_ISSUE_CODES) for i in issues
    )
    return Coverage(
        expected_count=len(expected_ids),
        received_count=len(predictions),
        scored_count=len(predicted_expected),
        missing_count=len(missing),
        duplicate_count=duplicate_count,
        unexpected_count=unexpected_count,
        valid=valid,
        issues=issues,
    )
