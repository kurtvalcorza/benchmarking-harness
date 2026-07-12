# Data Model: Computer-Vision Capability Benchmarks

Entities and value objects added or changed for US4 (image segmentation). Retro
stories US1–US3 changed no persisted schema (US2 added the read-only
`ModelListItem` projection; US3 the adapter only).

## Value objects (engine, not persisted as tables)

### Prediction — new `mask` channel

`engine.adapters.base.Prediction` gains a segmentation channel alongside the
existing detection (`boxes/scores/labels`) and classification (`label/class_scores`)
fields. Existing fields and their `to_dict`/`from_dict` are unchanged (FR-201).

| Field | Type | Notes |
|---|---|---|
| `masks` | `list[InstanceMask]` | per-instance predicted masks; empty for non-segmentation |

`InstanceMask` = `{ "label": str, "score": float, "rle": {"size": [h, w], "counts": str} }`.

- `canonicalize()` MUST carry `masks` through the label_map remap (remapping each
  `label`), not drop them when it rebuilds `Prediction` (FR-215).

### SegmentationAnnotation (dataset ground truth)

Per image in `annotations.json`, an object gains an optional mask; the segmentation
golden set requires it (FR-219):

```
{ "label": "vehicle", "rle": {"size": [h, w], "counts": "..."} }   # bbox optional
```

The dataset validator, today requiring `label` + optional `bbox`, MUST require a
valid `rle` for a segmentation golden set (R5/FR-219).

### PredictionCoverage — segmentation cases

The existing coverage record (expected/received/scored/missing/duplicate/
unexpected/valid/issues) applies to segmentation, with new typed `issues` codes:
`malformed_rle`, `mask_dim_mismatch`, `mask_out_of_range` (FR-216).

### EvaluatorProvenance — segmentation identity

Same shape as detection/classification (name, version, metric_contract,
configuration, dataset_checksum). For segmentation: `name = "segmentation-miou"`,
`configuration = { "metric": "miou", "reduction": "confidence-priority",
"mask": "coco-rle" }` (contracts/segmentation-metric.md).

## Persisted entities changed

### GoldenTestSet — per-class metric floors

Today the golden set persists `recall_floors: dict[str, float]` (per-class recall
minimums). Generalize so a segmentation set can declare **per-class IoU floors**
without a recall-only schema rejecting it (FR-214):

**LANDED (minimal, no migration):** the existing `recall_floors` JSON column is
the GENERIC per-class safety-floor store — recall floors for detection/
classification, IoU floors for segmentation. The manifest gains an `iou_floors`
field; a segmentation registration reads `iou_floors` (else `recall_floors`) and
stores it into that same column. Tier-2 (`safety_critical_floors`) checks the
stored floors against the class's per-class metric (`per_class_recall` /
`per_class_iou`). No new column ⇒ no Alembic migration.

Registration MUST store the floors; Tier-2 MUST check them against the class's
per-class metric.

### TierResult (append-only) — segmentation metrics + evidence

`TierResult.metrics` for a segmentation tier carries `miou`, `per_class_iou`
(`dict[str, float]`), `num_images`, `num_predictions`. `TierResult.evidence_digest`
+ `evidence_ref` point at the content-addressed reduced per-class masks (below).
`coverage` + `evaluator` travel as for the other classes (FR-208). Append-only is
unchanged.

### Segmentation mask evidence (content-addressed)

The reduced per-class semantic masks for a run are staged, sha256-digested, and
atomically published under `evidence/<digest>.json` (RLE bytes), compensated on
rollback — the same store as grounding evidence (FR-218). No raw image pixels
(Constitution II). The digest is recorded on the tier result so the verdict's
mask evidence is resolvable + reproducible (SC-004).

## Flag / verdict path (metric-typed)

The Tier-2 safety-floor breach today emits `FlagInput.safety_recall_breach` and
the trigger `safety_critical_recall_below_floor`. Generalize to a metric-typed
breach so a segmentation IoU-floor breach records an IoU trigger and the Model
Card reads "per-class IoU below floor", not "recall" (FR-214).

## Registry / thresholds (config, not schema)

- `engine/registry/registry.py` already maps `segmentation → Benchmark(dataset=
  "segmentation-sample", metric="miou", reference="Cityscapes mIoU")` — unchanged.
- `engine.metrics.SCORED_CLASSES` gains `segmentation` (FR-213).
- `thresholds.yaml` gains `segmentation.capability` / `segmentation.domain_stress`
  `miou` entries; `ratified: false` until governance sets a value → the run routes
  to `pending_adjudication` (FR-207).

## Transaction boundaries (unchanged mechanism)

Segmentation reuses the US4/002 atomic completion: the run, tier results, mask
evidence publish, and Model Card regenerate in one transaction or not at all; a
lost/duplicate dispatch is idempotent. No new transaction shape.

## Migration

**LANDED: no migration.** The reinterpret-`recall_floors` option was taken, so
`GoldenTestSet` gains no column; the mask evidence reuses the existing evidence
store (content-addressed under `results/evidence/<digest>.json`). No Alembic
migration is added to the 002 chain.
