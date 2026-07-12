# Contract: Segmentation Metric, Mask Validation, and Evidence

The Tier-1/Tier-2 contract for `segmentation`, parallel to
`002/contracts/metric-evidence.md` for detection/classification.

## Mask payload (predictions and ground truth)

A mask is COCO-style RLE:

```json
{ "size": [H, W], "counts": "<rle string>" }
```

A prediction instance:

```json
{ "label": "vehicle", "score": 0.83, "rle": { "size": [720, 1280], "counts": "..." } }
```

### Validation rules (typed coverage errors — FR-216)

- `malformed_rle` — `counts` does not decode, or `size` is missing/non-positive.
- `mask_dim_mismatch` — mask `size` ≠ the dataset image dimensions.
- `mask_out_of_range` — decoded mask area is negative/NaN or exceeds `H×W`.
- Coverage accounting (as classification/detection): expected = registered dataset
  size; a missing prediction is an empty mask (counted, lowers IoU); duplicate /
  unknown image ids are typed errors, never silently favorable.

A malformed mask MUST surface as a typed error, never a silent empty score or a
scorer exception.

## Metric identity

| Key | Definition |
|---|---|
| `miou` | mean over registered classes of per-class IoU |
| `per_class_iou` | `{ class: IoU }`, IoU = Σ intersection pixels / Σ union pixels over the dataset |
| `num_images` | registered dataset size (denominator) |
| `num_predictions` | predicted instances scored |

- IoU is computed on RLE via `pycocotools.mask` (intersection/union pixel counts
  accumulated dataset-wide, not mean-of-per-image).
- The gated capability metric is `miou` (`thresholds.yaml segmentation.capability`).

## Instance → semantic reduction (deterministic — FR-217)

Before scoring, per-instance predicted masks reduce to one per-class semantic mask
per image:

1. sort instances by `(score desc, index asc)`;
2. paint pixels in that order into a single label map — first claimant owns the
   pixel (cross-class overlap → higher score wins);
3. same-class instances union; unclaimed pixels = background (unscored).

The reduction MUST be deterministic for the same predictions (SC-004).

## Evidence (content-addressed — FR-218)

The reduced per-class masks are staged, sha256-digested, and atomically published
under `evidence/<digest>.json` (RLE bytes; no raw pixels). The tier result records
`evidence_digest` + `evidence_ref` + `coverage` + `evaluator` +
`dataset_checksum` so the verdict is resolvable and reproducible.

`EvaluatorProvenance` for segmentation:

```json
{
  "name": "segmentation-miou",
  "version": "0.1.0",
  "metric_contract": "harness-metrics/1",
  "configuration": { "metric": "miou", "reduction": "confidence-priority", "mask": "coco-rle" },
  "dataset_checksum": "<sha256>"
}
```

## Per-class floors (FR-214)

A segmentation golden set MAY declare per-class IoU floors. Tier-2 checks per-class
IoU against them; a breach routes to `pending_adjudication` with an **IoU** trigger
(not a recall trigger) and the Model Card reports "per-class IoU below floor".

## Forbidden substitutions

- A detection/classification-shaped dataset (label + bbox, no masks) MUST NOT
  register as a segmentation golden set (FR-219).
- Bounding-box IoU MUST NOT stand in for mask IoU.
- A confidence scalar MUST NOT stand in for a mask.
