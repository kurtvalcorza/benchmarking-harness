"""Task-appropriate metrics (T015, T051). Per-class recall is first-class:
Tier 2 surfaces it for every safety-critical class in the golden-set manifest
(FR-009/026) — never aggregate-only."""

from app.db.enums import ModelClass
from engine.adapters.base import Prediction
from engine.metrics.classification import evaluate_classification
from engine.metrics.coverage import compute_coverage
from engine.metrics.detection import evaluate_detection
from engine.metrics.segmentation import evaluate_segmentation

__all__ = [
    "SCORED_CLASSES",
    "METRIC_CONTRACT",
    "canonicalize",
    "evaluate",
    "evaluator_provenance",
    "safety_critical_recall",
    "safety_critical_floors",
    "compute_coverage",  # re-exported for the tier scorers
]

# Classes with an implemented scorer. The submission API refuses the other
# registered classes up front (clear 422) instead of infra-failing mid-run.
SCORED_CLASSES = {ModelClass.detection, ModelClass.classification, ModelClass.segmentation}

# Versioned metric contract identifier stamped into evaluator provenance (T036).
METRIC_CONTRACT = "harness-metrics/1"

# Per-class evaluator identity + configuration recorded on every scored result
# so a number is reproducible and its meaning unambiguous (data-model
# EvaluatorProvenance). Detection AP now comes from the pinned pycocotools
# reference evaluator (T034); the greedy approximation survives only as the
# non-gating `diagnostic_precision_recall_product` cross-check (T035).
_EVALUATORS: dict[ModelClass, dict] = {
    ModelClass.detection: {
        "name": "pycocotools.cocoeval",
        "metric_contract": METRIC_CONTRACT,
        "configuration": {
            "standard": "coco",
            "iou_thresholds": [round(0.5 + 0.05 * i, 2) for i in range(10)],
            "max_detections": [1, 10, 100],
            "ap_metric": "coco_ap_50_95",
            "diagnostic_metric": "diagnostic_precision_recall_product",
        },
    },
    ModelClass.classification: {
        "name": "harness.classification.topk",
        "metric_contract": METRIC_CONTRACT,
        "configuration": {"topk": [1, 5], "averaging": "macro", "missing_is_incorrect": True},
    },
    ModelClass.segmentation: {
        "name": "segmentation-miou",
        "metric_contract": METRIC_CONTRACT,
        "configuration": {
            "metric": "miou",
            "reduction": "confidence-priority",
            "mask": "coco-rle",
        },
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
    configuration = dict(base["configuration"])
    if model_class is ModelClass.detection:
        # record the PINNED reference-evaluator version so a COCO number is
        # reproducible against the exact implementation that produced it
        configuration["reference_version"] = _pycocotools_version()
    return {**base, "configuration": configuration, "version": harness_version}


def _pycocotools_version() -> str:
    try:
        from importlib.metadata import PackageNotFoundError, version

        try:
            return version("pycocotools")
        except PackageNotFoundError:
            return "unavailable"
    except Exception:  # noqa: BLE001 — provenance must never crash a run
        return "unknown"


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
        # segmentation masks carry a per-instance label too: remap it, never drop
        # the mask channel when rebuilding the Prediction (FR-215)
        remapped_masks = [
            {**m, "label": label_map.get(m.get("label"), m.get("label"))} for m in p.masks
        ]
        out.append(
            Prediction(
                image_id=p.image_id,
                boxes=p.boxes,
                scores=p.scores,
                labels=[label_map.get(lbl, lbl) for lbl in p.labels],
                label=label_map.get(p.label, p.label) if p.label else p.label,
                class_scores=merged_scores,
                masks=remapped_masks,
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
    if model_class is ModelClass.segmentation:
        return evaluate_segmentation(predictions, annotations)
    raise NotImplementedError(
        f"metrics for '{model_class.value}' land with its stand-in dataset (FR-025); "
        "the registry entry exists, the scorer is the remaining slot"
    )


def safety_critical_floors(
    metrics: dict,
    safety_classes: list[str],
    floors: dict[str, float],
    *,
    per_class_key: str,
    metric_name: str,
) -> tuple[dict[str, dict], bool]:
    """Metric-typed per-class safety-floor check (FR-009/012a/026/214).

    Reads the class's per-class metric (`per_class_recall` for detection/
    classification, `per_class_iou` for segmentation) and checks each safety
    class against its floor. Returns ({class: row}, any_breach); a safety class
    absent from the results counts as a breach (unmeasurable ≠ passing).

    Each row carries the generic `{metric, value, floor, ok}` AND the
    metric-named key (`recall`/`iou`) so both the metric-typed card path and the
    detection/classification back-compat readers work.
    """
    per_class = metrics.get(per_class_key, {})
    out: dict[str, dict] = {}
    breach = False
    for cls in safety_classes:
        floor = floors.get(cls)
        value = per_class.get(cls)
        ok = value is not None and floor is not None and value >= floor
        if not ok:
            breach = True
        out[cls] = {"metric": metric_name, "value": value, "floor": floor, "ok": ok, metric_name: value}
    return out, breach


def safety_critical_recall(
    metrics: dict, safety_classes: list[str], recall_floors: dict[str, float]
) -> tuple[dict[str, dict], bool]:
    """Detection/classification safety gate: per-class recall against its floor.
    A thin wrapper over :func:`safety_critical_floors` retained so existing
    callers/tests are unchanged."""
    return safety_critical_floors(
        metrics, safety_classes, recall_floors, per_class_key="per_class_recall", metric_name="recall"
    )
