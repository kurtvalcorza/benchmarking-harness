"""Task-appropriate metrics (T015, T051). Per-class recall is first-class:
Tier 2 surfaces it for every safety-critical class in the golden-set manifest
(FR-009/026) — never aggregate-only."""

from app.db.enums import ModelClass
from engine.adapters.base import Prediction
from engine.metrics.classification import evaluate_classification
from engine.metrics.coverage import compute_coverage
from engine.metrics.detection import evaluate_detection

__all__ = [
    "SCORED_CLASSES",
    "METRIC_CONTRACT",
    "canonicalize",
    "evaluate",
    "evaluator_provenance",
    "safety_critical_recall",
    "compute_coverage",  # re-exported for the tier scorers
]

# Classes with an implemented scorer. The submission API refuses the other
# registered classes up front (clear 422) instead of infra-failing mid-run.
SCORED_CLASSES = {ModelClass.detection, ModelClass.classification}

# Versioned metric contract identifier stamped into evaluator provenance (T036).
METRIC_CONTRACT = "harness-metrics/1"

# Per-class evaluator identity + configuration recorded on every scored result
# so a number is reproducible and its meaning unambiguous (data-model
# EvaluatorProvenance). The detection evaluator is the harness's dependency-light
# greedy-IoU AP — named honestly, NOT COCO; the pinned pycocotools reference
# evaluator is the remaining US2 slice (T034).
_EVALUATORS: dict[ModelClass, dict] = {
    ModelClass.detection: {
        "name": "harness.detection.greedy_iou_ap",
        "metric_contract": METRIC_CONTRACT,
        "configuration": {
            "iou_thresholds": [round(0.5 + 0.05 * i, 2) for i in range(10)],
            "matching": "greedy_per_image",
            "ap": "single_point_precision_times_recall",
        },
    },
    ModelClass.classification: {
        "name": "harness.classification.topk",
        "metric_contract": METRIC_CONTRACT,
        "configuration": {"topk": [1, 5], "averaging": "macro", "missing_is_incorrect": True},
    },
}


def evaluator_provenance(model_class: ModelClass, *, harness_version: str) -> dict:
    """Return EvaluatorProvenance (name/version/contract/configuration) for the
    class's scorer. `dataset_checksum` and `label_map_digest` are stamped by the
    caller that owns those values (orchestrator persistence)."""
    base = _EVALUATORS.get(model_class)
    if base is None:
        return {
            "name": f"harness.{model_class.value}.unimplemented",
            "metric_contract": METRIC_CONTRACT,
            "configuration": {},
            "version": harness_version,
        }
    return {**base, "configuration": dict(base["configuration"]), "version": harness_version}


def canonicalize(predictions: list[Prediction], label_map: dict[str, str]) -> list[Prediction]:
    """Map model-emitted labels onto the dataset's label space (F6).

    A COCO-trained detector emits `person`/`car`; a golden set may declare
    `pedestrian`/`vehicle`. The dataset manifest's `label_map` (emitted →
    dataset label) bridges the two — declared with the DATA, so adding a
    model vocabulary is a manifest edit, never a harness change (FR-020).
    Unmapped labels pass through unchanged."""
    if not label_map:
        return predictions
    out = []
    for p in predictions:
        # several emitted labels may collapse onto one canonical class
        # (car/truck/bus → vehicle): SUM their probabilities, never overwrite
        merged_scores: dict[str, float] = {}
        for k, v in p.class_scores.items():
            key = label_map.get(k, k)
            merged_scores[key] = merged_scores.get(key, 0.0) + v
        out.append(
            Prediction(
                image_id=p.image_id,
                boxes=p.boxes,
                scores=p.scores,
                labels=[label_map.get(lbl, lbl) for lbl in p.labels],
                label=label_map.get(p.label, p.label) if p.label else p.label,
                class_scores=merged_scores,
                extra=p.extra,
            )
        )
    return out


def evaluate(
    model_class: ModelClass,
    predictions: list[Prediction],
    annotations: dict[str, list[dict]],
) -> dict:
    if model_class is ModelClass.detection:
        return evaluate_detection(predictions, annotations)
    if model_class is ModelClass.classification:
        return evaluate_classification(predictions, annotations)
    raise NotImplementedError(
        f"metrics for '{model_class.value}' land with its stand-in dataset (FR-025); "
        "the registry entry exists, the scorer is the remaining slot"
    )


def safety_critical_recall(
    metrics: dict, safety_classes: list[str], recall_floors: dict[str, float]
) -> tuple[dict[str, dict], bool]:
    """Extract per-class recall for the manifest's safety-critical classes and
    check each against its floor (FR-009, FR-012a, FR-026).

    Returns ({class: {recall, floor, ok}}, any_breach). A safety class absent
    from the results counts as a breach (recall unmeasurable ≠ passing).
    """
    per_class = metrics.get("per_class_recall", {})
    out: dict[str, dict] = {}
    breach = False
    for cls in safety_classes:
        floor = recall_floors.get(cls)
        recall = per_class.get(cls)
        ok = recall is not None and floor is not None and recall >= floor
        if not ok:
            breach = True
        out[cls] = {"recall": recall, "floor": floor, "ok": ok}
    return out, breach
