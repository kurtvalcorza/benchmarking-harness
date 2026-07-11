# Contract: Metric Coverage and Grounding Evidence

**Version**: `002.1`
**Feature**: `002-production-hardening`

## Prediction batch validation

Every adapter result is validated before scoring.

```python
@dataclass(frozen=True)
class PredictionCoverage:
    expected_count: int
    received_count: int
    scored_count: int
    missing_count: int
    duplicate_count: int
    unexpected_count: int
    valid: bool
    issues: tuple[CoverageIssue, ...]

@dataclass(frozen=True)
class EvaluatorProvenance:
    name: str
    version: str
    metric_contract: str
    configuration: dict
    dataset_checksum: str
    label_map_digest: str | None = None
```
### Shared rules

- Image IDs are compared after the dataset loader's canonical normalization; adapters may not invent aliases.
- Scores, boxes, logits/probabilities, keypoints, masks, and metric inputs must contain only finite numeric values.
- Issue lists are bounded and include stable codes plus a small sample of offending IDs.
- Invalid adapter output is an infrastructure/evaluator failure, never a favorable model `fail` or partial score.

### Classification rules

- Expected IDs are all annotation keys with exactly one classification target.
- Exactly one prediction is accepted per expected ID.
- A missing prediction contributes one incorrect example and one false negative for its truth class.
- Duplicate or unexpected IDs invalidate the batch.
- `num_images`/denominator equals `expected_count`, not the number of returned predictions.

### Detection rules

- One `Prediction` envelope per expected image is required; it may contain zero boxes.
- Missing envelopes are normalized to an empty detection list and counted as missing coverage.
- `boxes`, `scores`, and `labels` lengths must match.
- Boxes use finite XYXY coordinates with positive area after deterministic image-bound clipping.
- Scores are finite in `[0,1]`.
- Duplicate/unexpected image IDs invalidate the batch.
- COCO AP uses confidence-ranked detections through the pinned reference evaluator.

## Metric identity

The following names are reserved:

- `coco_ap_50_95`: COCO-compatible AP averaged over IoU 0.50:0.05:0.95.
- `coco_ap_50`: COCO-compatible AP at IoU 0.50.
- `top1`, `top5`, `macro_f1`, `per_class_recall`: complete-dataset classification metrics.

Legacy `map_50_95` may be retained as an API alias during migration only if its evaluator provenance states `coco` and it is numerically identical to `coco_ap_50_95`. The previous single-point approximation must be renamed (for example `diagnostic_precision_recall_product`) and cannot be bound to a ratified COCO threshold.

## GroundingEvidence

```python
@dataclass(frozen=True)
class GroundingEvidence:
    status: Literal["measured", "unavailable"]
    method: str | None
    evaluator_version: str | None
    score: float | None
    sample_count: int
    target_ref: str | None
    evidence_ref: str | None
    evidence_digest: str | None
    unavailable_reason: str | None
```

### Measured evidence requirements

- `method` is in the configured approved-method registry.
- `score` is finite and within `[0,1]`.
- `sample_count` meets the configured method minimum.
- `target_ref` identifies the labeled target set and checksum.
- `evidence_ref` resolves to a per-sample or aggregate evidence artifact whose SHA-256 equals `evidence_digest`.
- Evaluator configuration and version are present in the Tier Result.

### Unavailable evidence requirements

- `score`, `method`, and evidence references are null.
- `unavailable_reason` is one of the contract values.
- Tier threshold evaluation returns unratified/unavailable, never pass.

### Forbidden substitutions

The following cannot be labeled or gated as visual grounding:

- confidence coverage or mean confidence;
- output entropy alone;
- parameter count, latency, throughput, or edge-deployability;
- an adapter-supplied scalar without reproducible method/sample/target evidence.

## Evidence JSON example

```json
{
  "coverage": {
    "expected_count": 100,
    "received_count": 100,
    "scored_count": 100,
    "missing_count": 0,
    "duplicate_count": 0,
    "unexpected_count": 0,
    "valid": true,
    "issues": []
  },
  "evaluator": {
    "name": "pycocotools.cocoeval",
    "version": "pinned-by-lock",
    "metric_contract": "002.1",
    "configuration": {
      "iou_thresholds": [0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95],
      "max_detections": [1, 10, 100]
    },
    "dataset_checksum": "<sha256>",
    "label_map_digest": "<sha256-or-null>"
  }
}
```
