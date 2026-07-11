"""T060 [US5] — GroundingEvidence schema + validation.

Grounding must be MEASURED from reproducible labeled localization evidence or
declared UNAVAILABLE. The forbidden substitutions (confidence, entropy,
parameter count, latency, an unverified scalar) are structurally impossible to
label as grounding here: the evaluator only accepts per-sample attribution
points/maps and matches them against labeled target boxes.
"""

import pytest

from engine.metrics.grounding import (
    GROUNDING_EVALUATOR_VERSION,
    GroundingEvidence,
    evaluate_grounding,
    unavailable,
)

METHODS = ("pointing_game", "energy_inside_region")

# 25 labeled targets across 5 images (>= the default 20-sample minimum)
ANNOTATIONS = {
    f"img_{i}": [{"label": "car", "bbox": [0, 0, 10, 10]} for _ in range(5)]
    for i in range(5)
}


def _points(hit_fraction: float) -> list[dict]:
    """One class-matched attribution point per target; the first `hit_fraction`
    land inside the box, the rest outside — deterministic, reproducible."""
    out = []
    idx = 0
    total = sum(len(v) for v in ANNOTATIONS.values())
    hits = round(total * hit_fraction)
    for image_id, objs in ANNOTATIONS.items():
        for _ in objs:
            inside = idx < hits
            point = [5, 5] if inside else [100, 100]
            out.append({"image_id": image_id, "label": "car", "point": point})
            idx += 1
    return out


def test_measured_evidence_has_all_required_fields():
    ev = evaluate_grounding(
        attributions=_points(0.8),
        annotations=ANNOTATIONS,
        approved_methods=METHODS,
        min_samples=20,
        target_ref="sha256:golden",
    )
    assert ev.status == "measured"
    assert ev.method == "pointing_game"
    assert ev.evaluator_version == GROUNDING_EVALUATOR_VERSION
    assert ev.score == pytest.approx(0.8, abs=1e-6)
    assert 0.0 <= ev.score <= 1.0
    assert ev.sample_count == 25
    assert ev.target_ref == "sha256:golden"
    assert ev.evidence_digest and len(ev.evidence_digest) == 64  # sha256 hex


def test_missing_attribution_is_unavailable_not_zero():
    ev = evaluate_grounding(
        attributions=None,
        annotations=ANNOTATIONS,
        approved_methods=METHODS,
        min_samples=20,
        target_ref=None,
    )
    assert ev.status == "unavailable"
    assert ev.unavailable_reason == "missing_attribution"
    assert ev.score is None  # never a fabricated 0.0 that could be thresholded


def test_insufficient_samples_cannot_be_measured():
    small = {"img_0": [{"label": "car", "bbox": [0, 0, 10, 10]}]}
    ev = evaluate_grounding(
        attributions=[{"image_id": "img_0", "label": "car", "point": [5, 5]}],
        annotations=small,
        approved_methods=METHODS,
        min_samples=20,
        target_ref="sha256:golden",
    )
    assert ev.status == "unavailable"
    assert ev.unavailable_reason == "insufficient_samples"
    assert ev.score is None


def test_confidence_scalar_cannot_pose_as_grounding():
    """A model that supplies only a confidence-like scalar (no per-sample
    attribution point) yields no usable localization evidence."""
    scalar_only = [{"image_id": "img_0", "label": "car", "confidence": 0.99}]
    ev = evaluate_grounding(
        attributions=scalar_only,
        annotations=ANNOTATIONS,
        approved_methods=METHODS,
        min_samples=20,
        target_ref="sha256:golden",
    )
    assert ev.status == "unavailable"  # no point/map → not scorable as grounding


def test_energy_inside_region_used_when_points_absent():
    maps = [
        {"image_id": f"img_{i}", "label": "car", "energy_inside": 0.7}
        for i in range(25)
    ]
    ev = evaluate_grounding(
        attributions=maps,
        annotations=ANNOTATIONS,
        approved_methods=("energy_inside_region",),
        min_samples=20,
        target_ref="sha256:golden",
    )
    assert ev.status == "measured"
    assert ev.method == "energy_inside_region"
    assert ev.score == pytest.approx(0.7, abs=1e-6)


def test_out_of_range_energy_is_invalid_not_measured():
    """Per-sample energy fractions must be finite in [0,1]; an out-of-range value
    cannot average into a measured pass."""
    maps = [
        {"image_id": f"img_{i}", "label": "car", "energy_inside": e}
        for i, e in enumerate([2.0, 0.0, -0.5] + [0.5] * 22)
    ]
    ev = evaluate_grounding(
        attributions=maps,
        annotations=ANNOTATIONS,
        approved_methods=("energy_inside_region",),
        min_samples=20,
        target_ref="sha256:golden",
    )
    assert ev.status == "unavailable"
    assert ev.unavailable_reason == "invalid_evidence"
    assert ev.score is None


def test_unavailable_reason_is_validated():
    assert unavailable("unsupported_model_class").unavailable_reason == "unsupported_model_class"
    with pytest.raises(ValueError):
        unavailable("mean_confidence")  # not a contract reason


def test_to_dict_shape_matches_contract():
    ev = GroundingEvidence(status="unavailable", unavailable_reason="unsupported_model_class")
    d = ev.to_dict()
    assert set(d) == {
        "status",
        "method",
        "evaluator_version",
        "score",
        "sample_count",
        "target_ref",
        "evidence_ref",
        "evidence_digest",
        "unavailable_reason",
    }
