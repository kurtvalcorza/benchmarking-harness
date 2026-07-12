# Contract Delta: Inference Adapter — Segmentation

Extends the feature-001 `InferenceAdapter` contract for the segmentation modality.
Detection and classification obligations are unchanged.

## Prediction shape

For `model_class == segmentation`, `predict()` returns one `Prediction` per image
carrying the `masks` channel (see data-model.md):

```
Prediction(image_id=..., masks=[
  { "label": <str>, "score": <float>, "rle": { "size": [H, W], "counts": <str> } },
  ...
])
```

- Masks MUST be COCO-style RLE (`pycocotools.mask`), sized to the image.
- `boxes`/`labels`/`label`/`class_scores` remain empty for a pure segmentation
  prediction; the adapter MUST NOT overload them.
- Deterministic for the same weights + images + seed (Constitution).

## PyTorch adapter — Ultralytics `-seg`

- Load via `YOLO(artifact_ref)` first (the YOLO-first pattern established for
  classification in PR #11), then require `net.task == "segment"`; a checkpoint
  whose task is not `segment` under the segmentation class MUST raise
  `AdapterError` with a clear message.
- Read masks from `results[i].masks` (RLE-encode the polygon/mask output) and
  the class + confidence from `results[i].boxes`.
- All load + inference run inside the no-egress sandbox (untrusted `.pt`).

## Stub adapter — deterministic segmentation

- The stub emits deterministic masks derived from the dataset ground truth
  (hash-seeded hit/miss like detection), so the real scorer runs, degradation
  under perturbation is real, and identical inputs reproduce identical masks
  (SC-004) — enabling the offline demo + tests without the ml extra.

## Rejection semantics

- A bare/incompatible checkpoint that cannot load as an Ultralytics `-seg` model
  MUST surface a clear `AdapterError` (infra condition), never a silent empty
  mask set.
