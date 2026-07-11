"""Visual-grounding evaluation (T063, US5).

Tier 3 grounding must be MEASURED from reproducible labeled localization
evidence or declared explicitly UNAVAILABLE — never approximated from
confidence, entropy, parameter count, latency, or an unverified adapter scalar
(metric-evidence.md §Forbidden substitutions). This module implements the
approved-method registry and the localization evaluators, plus the
`GroundingEvidence` value object the Tier 3 result carries.

Approved methods (configurable via HARNESS_GROUNDING_METHODS):

- ``pointing_game``: the standard interpretability metric — for each labeled
  target instance, does the model's attribution point of the SAME class fall
  inside the target box? score = hits / targets.
- ``energy_inside_region``: fraction of a per-sample attribution map's energy
  that falls inside the target box, averaged. Requires real attribution maps;
  when only points are available this method is not applicable and the evaluator
  falls through to the next configured method.

A model class without localizable targets (e.g. whole-image classification)
yields ``unavailable(unsupported_model_class)`` — it can never auto-pass Tier 3
and is routed to human adjudication (fail-closed).
"""

import hashlib
import json
from dataclasses import dataclass, field
from math import isfinite

GROUNDING_EVALUATOR_VERSION = "grounding/1"

UNAVAILABLE_REASONS = frozenset(
    {
        "unsupported_framework",
        "unsupported_model_class",
        "missing_attribution",
        "insufficient_samples",
        "invalid_evidence",
    }
)


@dataclass(frozen=True)
class GroundingEvidence:
    """Tier 3 grounding result (metric-evidence.md §GroundingEvidence)."""

    status: str  # "measured" | "unavailable"
    method: str | None = None
    evaluator_version: str | None = None
    score: float | None = None
    sample_count: int = 0
    target_ref: str | None = None
    evidence_ref: str | None = None
    evidence_digest: str | None = None
    unavailable_reason: str | None = None
    # raw per-sample attribution, persisted by the orchestrator as the evidence
    # artifact that `evidence_ref`/`evidence_digest` address (never scored again)
    samples: list = field(default_factory=list, compare=False)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "method": self.method,
            "evaluator_version": self.evaluator_version,
            "score": self.score,
            "sample_count": self.sample_count,
            "target_ref": self.target_ref,
            "evidence_ref": self.evidence_ref,
            "evidence_digest": self.evidence_digest,
            "unavailable_reason": self.unavailable_reason,
        }

    @property
    def measured(self) -> bool:
        return self.status == "measured"


def _inside(point: list[float], box: list[float]) -> bool:
    x, y = point[0], point[1]
    return box[0] <= x <= box[2] and box[1] <= y <= box[3]


def _attribution_points(attributions: list[dict]) -> dict[str, list[tuple]]:
    by_image: dict[str, list[tuple]] = {}
    for a in attributions:
        pt = a.get("point")
        if pt is None or len(pt) < 2 or not all(isfinite(v) for v in pt[:2]):
            continue
        by_image.setdefault(a.get("image_id"), []).append((a.get("label"), pt))
    return by_image


def _pointing_game(
    attributions: list[dict], annotations: dict[str, list[dict]]
) -> tuple[float | None, int]:
    """(score, sample_count) — fraction of target instances whose class-matched
    attribution point lands inside the target box."""
    by_image = _attribution_points(attributions)
    if not by_image:
        return None, 0  # no point-based attribution → method not applicable
    total = 0
    hits = 0
    for image_id, objs in annotations.items():
        for obj in objs:
            if "bbox" not in obj:
                continue
            total += 1
            box = obj["bbox"]
            if any(
                lbl == obj["label"] and _inside(pt, box)
                for lbl, pt in by_image.get(image_id, [])
            ):
                hits += 1
    if total == 0:
        return None, 0
    return hits / total, total


def _energy_inside_region(
    attributions: list[dict], annotations: dict[str, list[dict]]
) -> tuple[float | None, int]:
    """(score, sample_count) — mean fraction of each attribution map's energy
    inside its target box. Requires per-sample maps; not applicable to
    point-only attribution."""
    maps = [a for a in attributions if a.get("energy_inside") is not None]
    if not maps:
        return None, 0
    # each energy fraction must be finite in [0,1] (contract §Shared rules); an
    # out-of-range value is invalid input and cannot contribute a valid average
    fractions = [float(a["energy_inside"]) for a in maps]
    if not all(isfinite(f) and 0.0 <= f <= 1.0 for f in fractions):
        return float("nan"), len(fractions)  # → caught by the [0,1] guard → invalid_evidence
    return sum(fractions) / len(fractions), len(fractions)


_METHODS = {
    "pointing_game": _pointing_game,
    "energy_inside_region": _energy_inside_region,
}


def _samples_digest(attributions: list[dict]) -> str:
    body = json.dumps(attributions, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def evaluate_grounding(
    *,
    attributions: list[dict] | None,
    annotations: dict[str, list[dict]],
    approved_methods: tuple[str, ...],
    min_samples: int,
    target_ref: str | None,
) -> GroundingEvidence:
    """Score grounding with the first applicable approved method, or return an
    explicit `unavailable` verdict. Never falls back to a forbidden proxy."""
    if not attributions:
        return GroundingEvidence(status="unavailable", unavailable_reason="missing_attribution")

    for method in approved_methods:
        fn = _METHODS.get(method)
        if fn is None:
            continue  # a configured method with no implementation is skipped
        score, n = fn(attributions, annotations)
        if score is None or n == 0:
            continue  # method not applicable to this evidence → try the next
        if n < min_samples:
            # contract §Unavailable: null method/score AND evidence/target refs;
            # sample_count is the only diagnostic retained
            return GroundingEvidence(
                status="unavailable",
                unavailable_reason="insufficient_samples",
                sample_count=n,
            )
        if not (isfinite(score) and 0.0 <= score <= 1.0):
            return GroundingEvidence(
                status="unavailable",
                unavailable_reason="invalid_evidence",
                sample_count=n,
            )
        return GroundingEvidence(
            status="measured",
            method=method,
            evaluator_version=GROUNDING_EVALUATOR_VERSION,
            score=round(score, 4),
            sample_count=n,
            target_ref=target_ref,
            evidence_digest=_samples_digest(attributions),
            samples=list(attributions),
        )

    # attribution present but no approved method could use it
    return GroundingEvidence(status="unavailable", unavailable_reason="missing_attribution")


def unavailable(reason: str, *, method: str | None = None) -> GroundingEvidence:
    """Construct an explicit unavailable verdict with a validated reason."""
    if reason not in UNAVAILABLE_REASONS:
        raise ValueError(f"unknown grounding unavailable_reason {reason!r}")
    return GroundingEvidence(status="unavailable", unavailable_reason=reason, method=method)
