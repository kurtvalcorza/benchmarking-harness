"""Tier 3 — operational & safety (T029, FR-022).

POC scope (analyze remediation): interpretability (visual grounding) + resource
profile. Robustness / drift / shortcut probes are de-scoped (spec Out of Scope).

Grounding: adapters that expose a grounding score (stub models; pytorch models
evaluated with the `ml` extra's Grad-CAM pipeline) report it directly; otherwise
a confidence-coverage proxy is computed and the method is recorded honestly in
the metrics — never fabricated (Constitution V).

Resource profile: latency/throughput measured from the sandboxed clean-set
inference; parameters/memory from the adapter descriptor; edge profile is
informational, not an automatic fail (spec edge case).
"""

from dataclasses import dataclass

from app.db.enums import ModelClass, Tier
from engine.datasets import resolve
from engine.registry.registry import get_benchmark
from engine.sandbox.runner import run_inference
from engine.tiers.tier1_capability import TierOutcome, check_threshold

EDGE_MAX_PARAMS = 60_000_000
EDGE_MAX_LATENCY_MS = 250.0


@dataclass
class _Grounding:
    score: float | None
    method: str


def _grounding(descriptor: dict, predictions: list[dict]) -> _Grounding:
    extra = descriptor.get("extra") or {}
    if extra.get("grounding") is not None:
        return _Grounding(score=float(extra["grounding"]), method="adapter_reported")
    scores = [s for p in predictions for s in (p.get("scores") or [])]
    scores += [max(p["class_scores"].values()) for p in predictions if p.get("class_scores")]
    if not scores:
        return _Grounding(score=None, method="unavailable")
    coverage = sum(1 for s in scores if s >= 0.5) / len(scores)
    return _Grounding(score=round(coverage, 4), method="confidence_coverage_proxy")


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
    grounding = _grounding(desc, job.predictions)
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
        "grounding_score": grounding.score,
        "grounding_method": grounding.method,
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
    return TierOutcome(
        tier=Tier.operational_safety,
        metrics=m,
        threshold=thr_dict,
        passed=passed,
        unratified=unratified,
        evidence={"sandbox_mode": job.sandbox_mode, "timing": timing},
    )
