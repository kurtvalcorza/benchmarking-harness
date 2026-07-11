"""T061 [US5] — Tier 3 grounding regressions.

Confidence-only output, insufficient localization samples, and poor grounding
must all be prevented from silently passing Tier 3. Measured grounding evidence
(reproducible attribution scored against labeled targets) is the ONLY thing that
can pass; everything else is explicitly unavailable and routed to adjudication.
"""

import json

from tests.conftest import HEALTHY_DET, det_manifest, register_golden, submit_model


def _tier3(client, version_id: str) -> dict:
    hist = client.get(f"/models/{version_id}/history").json()
    run = client.get(f"/runs/{hist[0]['id']}").json()
    return next(t for t in run["tier_results"] if t["tier"] == "operational_safety")


def _stub(tmp_path, name: str, **spec) -> "object":
    p = tmp_path / f"{name}.stub.json"
    p.write_text(
        json.dumps(
            {"kind": "stub-model", "task": "detection", "skill": 0.95, "param_count": 3_500_000, **spec}
        )
    )
    return p


def test_well_grounded_detector_passes_on_measured_evidence(client):
    register_golden(client, det_manifest())
    mv = submit_model(client, weights_path=HEALTHY_DET, name="wg", sources=["s"])
    assert mv["status"] == "approved"
    t3 = _tier3(client, mv["id"])
    g = t3["metrics"]["grounding"]
    assert g["status"] == "measured"
    assert g["method"] == "pointing_game"
    assert g["score"] >= 0.30 and g["sample_count"] >= 20
    assert g["target_ref"] and g["evidence_ref"] and g["evidence_digest"]


def test_confidence_only_model_cannot_pass_tier3(client, tmp_path):
    """A model that emits detections + confidence but NO attribution has no
    measurable grounding — unavailable, never a confidence-coverage pass."""
    register_golden(client, det_manifest())
    weights = _stub(tmp_path, "confonly", emit_attribution=False)
    mv = submit_model(client, weights_path=weights, name="confonly", sources=["s"])
    assert mv["status"] == "pending_adjudication"
    t3 = _tier3(client, mv["id"])
    assert t3["metrics"]["grounding"]["status"] == "unavailable"
    assert t3["metrics"]["grounding"]["unavailable_reason"] == "missing_attribution"
    assert t3["metrics"]["grounding_score"] is None
    assert t3["passed"] is None  # unratified/unavailable — never a pass


def test_insufficient_samples_cannot_pass_tier3(client, tmp_path, monkeypatch):
    """Below the configured minimum sample count, grounding is unavailable even
    when attribution is present."""
    # above any plausible benchmark object count (the resolved set is ~51 in CI
    # but larger where real fetched data is present) so the assertion is stable
    monkeypatch.setenv("HARNESS_GROUNDING_MIN_SAMPLES", "1000000")
    register_golden(client, det_manifest())
    mv = submit_model(client, weights_path=HEALTHY_DET, name="fewsamples", sources=["s"])
    assert mv["status"] == "pending_adjudication"
    t3 = _tier3(client, mv["id"])
    assert t3["metrics"]["grounding"]["status"] == "unavailable"
    assert t3["metrics"]["grounding"]["unavailable_reason"] == "insufficient_samples"
    assert t3["metrics"]["grounding_score"] is None


def test_poorly_grounded_detector_fails_tier3(client, tmp_path):
    """Measured but below the ratified floor → a real Tier 3 failure (grounding
    is a genuine gate, not a rubber stamp)."""
    register_golden(client, det_manifest())
    weights = _stub(tmp_path, "poorlygrounded", grounding=0.02)
    mv = submit_model(client, weights_path=weights, name="poorlygrounded", sources=["s"])
    assert mv["status"] != "approved"
    t3 = _tier3(client, mv["id"])
    g = t3["metrics"]["grounding"]
    assert g["status"] == "measured"
    assert g["score"] < 0.30
    assert t3["passed"] is False
