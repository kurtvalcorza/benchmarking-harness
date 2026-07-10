"""Task-appropriate metrics (T015, T051). Per-class recall is first-class:
Tier 2 surfaces it for every safety-critical class in the golden-set manifest
(FR-009/026) — never aggregate-only."""

from app.db.enums import ModelClass
from engine.adapters.base import Prediction
from engine.metrics.classification import evaluate_classification
from engine.metrics.detection import evaluate_detection


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
