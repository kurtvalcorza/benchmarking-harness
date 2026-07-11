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
    """Non-finite (NaN/inf) scores or class probabilities → typed issues."""
    issues: list[dict] = []
    for p in predictions:
        bad = any(not _finite(s) for s in p.scores) or any(
            not _finite(v) for v in p.class_scores.values()
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

    valid = duplicate_count == 0 and unexpected_count == 0 and not any(
        i["code"] in ("nan_score", "malformed_output") for i in issues
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
