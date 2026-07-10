"""Tier 1 — general capability (T027, FR-005/006/007).

The benchmark is selected from the model-class registry (never hardcoded);
inference executes inside the no-egress sandbox (D1); the configured Minimum
Viable Competence threshold decides pass/fail (unratified → pending, FR-012b).
"""

from dataclasses import dataclass, field

from app.db.enums import ModelClass, Tier
from engine import metrics as metrics_mod
from engine.adapters.base import Prediction
from engine.datasets import resolve
from engine.registry.registry import get_benchmark
from engine.sandbox.runner import JobResult, run_inference


@dataclass
class TierOutcome:
    tier: Tier
    metrics: dict
    threshold: dict | None
    passed: bool | None  # None → threshold unset/unratified (pending)
    condition: str | None = None
    evidence: dict = field(default_factory=dict)
    adapter_error: str | None = None
    unratified: bool = False


def run_tier1(*, framework: str, artifact: str, model_class: ModelClass, threshold) -> TierOutcome:
    bench = get_benchmark(model_class)
    dataset = resolve(bench.dataset)
    job: JobResult = run_inference(
        framework=framework,
        artifact=artifact,
        model_class=model_class.value,
        dataset_root=str(dataset.root),
    )
    if job.adapter_error:
        return TierOutcome(
            tier=Tier.capability,
            metrics={},
            threshold=None,
            passed=None,
            adapter_error=job.adapter_error,
        )
    preds = [Prediction.from_dict(p) for p in job.predictions]
    m = metrics_mod.evaluate(model_class, preds, dataset.annotations)
    m["benchmark"] = bench.reference
    m["dataset"] = bench.dataset
    passed, thr_dict, unratified = check_threshold(m, threshold)
    return TierOutcome(
        tier=Tier.capability,
        metrics=m,
        threshold=thr_dict,
        passed=passed,
        unratified=unratified,
        evidence={
            "sandbox_mode": job.sandbox_mode,
            "timing": job.timing,
            "descriptor": job.descriptor,
            "num_predictions": len(preds),
        },
    )


def check_threshold(metrics: dict, threshold) -> tuple[bool | None, dict | None, bool]:
    """(passed, threshold_as_recorded, unratified). Unset/unratified thresholds
    can never silently pass (FR-012b): passed=None routes to adjudication."""
    if threshold is None:
        return None, None, True
    thr_dict = {
        "metric": threshold.metric,
        "minimum": threshold.minimum,
        "ratified": threshold.ratified,
    }
    if not threshold.ratified:
        return None, thr_dict, True
    value = metrics.get(threshold.metric)
    if value is None:
        return None, thr_dict, True
    return bool(value >= threshold.minimum), thr_dict, False
