"""Tier 3 — operational & safety (T064, FR-022, US5).

POC scope (analyze remediation): interpretability (visual grounding) + resource
profile. Robustness / drift / shortcut probes are de-scoped (spec Out of Scope).

Grounding (US5): MEASURED from reproducible labeled localization evidence — the
adapter's per-detection attribution points scored by the approved-method
evaluator (pointing game) against the benchmark's target boxes — or declared
explicitly UNAVAILABLE. It is NEVER approximated from confidence, entropy,
parameter count, latency, or an unverified adapter scalar (metric-evidence.md
§Forbidden substitutions). An unavailable verdict leaves `grounding_score`
unset, so Tier 3 can never auto-pass and the run is routed to human adjudication
(fail-closed).

Resource profile: latency/throughput measured from the sandboxed clean-set
inference; parameters/memory from the adapter descriptor; edge profile is
informational, not an automatic fail (spec edge case).
"""

from app.db.enums import ModelClass, Tier
from app.services.config import load_config
from engine.datasets import resolve
from engine.metrics import grounding as grounding_metrics
from engine.registry.registry import get_benchmark
from engine.sandbox.runner import run_inference
from engine.tiers.tier1_capability import TierOutcome, check_threshold

EDGE_MAX_PARAMS = 60_000_000
EDGE_MAX_LATENCY_MS = 250.0

# Model classes with localizable targets (boxes) the pointing-game evaluator can
# score. Whole-image classification has no localization target → unavailable.
LOCALIZATION_CLASSES = {ModelClass.detection}


def _grounding_evidence(
    model_class: ModelClass, predictions: list[dict], dataset
) -> grounding_metrics.GroundingEvidence:
    if model_class not in LOCALIZATION_CLASSES:
        # no localizable target for this class → cannot MEASURE visual grounding
        return grounding_metrics.unavailable("unsupported_model_class")
    attributions: list[dict] = []
    for p in predictions:
        image_id = p.get("image_id")
        for a in p.get("attribution") or []:
            attributions.append({"image_id": image_id, **a})
    cfg = load_config()
    return grounding_metrics.evaluate_grounding(
        attributions=attributions,
        annotations=dataset.annotations,
        approved_methods=cfg.grounding_methods,
        min_samples=cfg.grounding_min_samples,
        target_ref=dataset.checksum(),
    )


def run_tier3(
    *, framework: str, artifact: str, model_class: ModelClass, threshold
) -> TierOutcome:
    # profile against the class's registry benchmark set (clean data)
    dataset = resolve(get_benchmark(model_class).dataset)
    job = run_inference(
        framework=framework,
        artifact=artifact,
        model_class=model_class.value,
        dataset_root=str(dataset.root),
    )
    if job.adapter_error:
        return TierOutcome(
            tier=Tier.operational_safety,
            metrics={},
            threshold=None,
            passed=None,
            adapter_error=job.adapter_error,
        )
    timing = job.timing
    desc = job.descriptor
    grounding = _grounding_evidence(model_class, job.predictions, dataset)
    params = desc.get("param_count")
    latency = timing.get("latency_ms_per_image")
    predict_s = timing.get("predict_s") or 0
    n = timing.get("num_images") or 0
    edge_deployable = (
        params is not None
        and latency is not None
        and params <= EDGE_MAX_PARAMS
        and latency <= EDGE_MAX_LATENCY_MS
    )
    m = {
        # gated metric: the MEASURED grounding score, or None when unavailable
        # (check_threshold then returns pending → adjudication, never a pass)
        "grounding_score": grounding.score,
        "grounding": grounding.to_dict(),
        "grounding_status": grounding.status,
        "latency_ms_per_image": latency,
        "throughput_images_per_s": round(n / predict_s, 2) if predict_s else None,
        "param_count": params,
        "est_memory_mb": round(params * 4 / 1e6, 1) if params else None,
        "edge_profile": {
            "edge_deployable": bool(edge_deployable),
            "max_params": EDGE_MAX_PARAMS,
            "max_latency_ms": EDGE_MAX_LATENCY_MS,
        },
        "framework": desc.get("framework"),
        "framework_version": desc.get("framework_version"),
    }
    passed, thr_dict, unratified = check_threshold(m, threshold)
    # unavailable grounding can NEVER auto-pass — route to adjudication
    # (unratified/pending), defence in depth on top of the null gated metric
    if not grounding.measured:
        passed, unratified = None, True
    return TierOutcome(
        tier=Tier.operational_safety,
        metrics=m,
        threshold=thr_dict,
        passed=passed,
        unratified=unratified,
        evidence={
            "sandbox_mode": job.sandbox_mode,
            "timing": timing,
            # raw per-sample attribution → persisted by the orchestrator as the
            # evidence artifact grounding.evidence_ref/digest address (T066)
            "grounding_samples": grounding.samples,
        },
    )
