"""Tier 2 — local-context stress (T028, T050, T051; FR-008/009/018/026).

Scores the model on the versioned Golden Test Set clean, then under each
adverse condition SEPARATELY (one result per condition), reports the
worst-case drop from clean, and surfaces per-class recall for the manifest's
safety-critical classes against their floors. A floor breach on ANY condition
(clean included) flags the run for human adjudication (FR-012a).
"""

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from app.db.enums import Condition, ModelClass, Tier
from engine import metrics as metrics_mod
from engine.adapters.base import Prediction
from engine.datasets import Dataset
from engine.perturb.transforms import perturb_dataset
from engine.sandbox.runner import run_inference
from engine.tiers.tier1_capability import HARNESS_VERSION, TierOutcome, check_threshold


@dataclass
class Tier2Result:
    outcomes: list[TierOutcome] = field(default_factory=list)  # one per condition
    safety_breach: bool = False
    worst_case_drop: dict | None = None
    adapter_error: str | None = None
    unratified: bool = False

    @property
    def passed(self) -> bool | None:
        vals = [o.passed for o in self.outcomes]
        if any(v is False for v in vals):
            return False
        if any(v is None for v in vals):
            return None
        return True


def run_tier2(
    *,
    framework: str,
    artifact: str,
    model_class: ModelClass,
    golden_root: str,
    conditions: list[Condition],
    safety_classes: list[str],
    recall_floors: dict[str, float],
    threshold,
    label_map: dict[str, str] | None = None,
) -> Tier2Result:
    golden = Dataset(root=Path(golden_root))
    annotations = golden.annotations
    result = Tier2Result()
    ordered = [Condition.clean] + [c for c in conditions if c is not Condition.clean]
    primary = threshold.metric if threshold else None
    clean_score: float | None = None

    # perturbed copies must be daemon-visible when the sandbox runs via a host
    # docker daemon — same workdir contract as engine.sandbox.runner
    workdir = os.environ.get("HARNESS_SANDBOX_WORKDIR")
    if workdir:
        Path(workdir).mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="harness-perturb-", dir=workdir or None) as tmp:
        for cond in ordered:
            if cond is Condition.clean:
                cond_root = golden.root
            else:
                cond_root = perturb_dataset(golden.root, cond, Path(tmp) / cond.value)
            job = run_inference(
                framework=framework,
                artifact=artifact,
                model_class=model_class.value,
                dataset_root=str(cond_root),
            )
            if job.adapter_error:
                result.adapter_error = job.adapter_error
                return result
            preds = [Prediction.from_dict(p) for p in job.predictions]
            # F6: map model-emitted labels onto the golden set's label space
            preds = metrics_mod.canonicalize(preds, label_map or {})
            coverage = metrics_mod.compute_coverage(preds, annotations).to_dict()
            m = metrics_mod.evaluate(model_class, preds, annotations)
            per_class, breach = metrics_mod.safety_critical_recall(
                m, safety_classes, recall_floors
            )
            m["safety_critical"] = per_class  # FR-009: never aggregate-only
            result.safety_breach = result.safety_breach or breach
            passed, thr_dict, unratified = check_threshold(m, threshold)
            result.unratified = result.unratified or unratified
            result.outcomes.append(
                TierOutcome(
                    tier=Tier.domain_stress,
                    condition=cond.value,
                    metrics=m,
                    threshold=thr_dict,
                    passed=passed,
                    unratified=unratified,
                    coverage=coverage,
                    evaluator=metrics_mod.evaluator_provenance(
                        model_class, harness_version=HARNESS_VERSION
                    ),
                    evidence={"sandbox_mode": job.sandbox_mode, "timing": job.timing},
                )
            )
            if primary and m.get(primary) is not None:
                if cond is Condition.clean:
                    clean_score = m[primary]
                elif clean_score is not None:
                    drop = round(clean_score - m[primary], 4)
                    if result.worst_case_drop is None or drop > result.worst_case_drop["drop"]:
                        result.worst_case_drop = {
                            "metric": primary,
                            "clean": clean_score,
                            "worst_condition": cond.value,
                            "worst_score": m[primary],
                            "drop": drop,
                        }

    if result.worst_case_drop and result.outcomes:
        # stamp the degradation summary on the clean row so it travels with the run
        result.outcomes[0].metrics["worst_case_drop"] = result.worst_case_drop
    return result
