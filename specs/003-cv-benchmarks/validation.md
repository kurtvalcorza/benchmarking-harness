# Validation Record: Computer-Vision Capability Benchmarks (003 / US4)

Mirrors 002's validation record. US1–US3 (retro) were validated when they landed
(PRs #9/#10/#11); this records the **image-segmentation (US4)** validation.

## Automated suite (T060)

- `cd backend && pytest -q` → **229 passed, 2 skipped** (the 2 skips are the live
  docker-sandbox probes, which skip without a Docker daemon). No detection or
  classification regression (FR-212).
- Constitution gates green: `pytest tests/contract/test_no_restricted_data.py
  test_no_auto_approval.py test_sandbox_no_egress.py` → pass.
- `ruff check` on the changed backend modules → clean.

New segmentation coverage:
- `tests/unit/test_segmentation_miou.py` — perfect / partial (hand-computed
  16/48) / missing (complete-accounting 0.5) IoU; bbox-IoU cannot stand in for
  mask IoU; same-class union; cross-class overlap resolved by confidence;
  reduction order-independence (SC-004); `malformed_rle` / `mask_dim_mismatch`
  coverage errors invalidate the run.
- `tests/unit/test_pytorch_adapter.py::test_segmentation_rejects_non_seg_checkpoint`
  — a non-`-seg` / bare checkpoint under the segmentation class is rejected clearly.
- `tests/integration/test_segmentation_eval.py` — a stub-seg submission scores
  mIoU end-to-end via the registry, routes to `pending_adjudication` (unratified
  threshold), Tier-2 reports metric-typed (`iou`) per-class safety floors, mask
  evidence is content-addressed; a mask-less dataset is rejected as segmentation
  (FR-219) and IoU floors are stored (FR-214).

## Live real-model run (T061) — `yolov8n-seg.pt`

Ultralytics `yolov8n-seg.pt` (COCO, task=`segment`, 80 classes) on the
`segmentation-sample` benchmark, `.venv` with the `[ml]` extra (torch 2.11,
ultralytics 8.x), RTX 5070 Ti host:

**Adapter + scorer (direct):**
- Load → `task=segment`, `is_yolo=True`, 80 class names.
- Predict → 16 images, 12 per-instance masks emitted, each COCO-RLE at the
  original image resolution (`size=[96, 96]`, `retina_masks`).
- Canonicalize (COCO `person/car/... → pedestrian/vehicle/traffic_sign`) + score
  → `miou=0.0`, `per_class_iou={pedestrian:0.0, vehicle:0.0, traffic_sign:0.0}`,
  `num_images=16`, `num_predictions=12`. Coverage `valid=True`, 16/16 scored.
  The **0.0 is honest**: a COCO segmenter emits `clock`/`train`/`stop sign` on
  the synthetic ellipse images, none overlapping the road-scene ground truth —
  the *path* (load → per-instance masks → deterministic reduction → dataset-wide
  pixel IoU → coverage) is proven, exactly as `yolov8n.pt` proved the detection
  path on the sample (`coco_ap_50_95=0.2022`, rejected). A meaningful non-zero
  score needs real road-scene masks (`scripts/fetch_open_images.py --class
  segmentation`).

**Through the no-egress sandbox (`run_inference`, subprocess mode):**
- `adapter_error=None`, 16 predictions, 8 with masks, RLE `size=[96, 96]`, mask
  keys `{label, score, rle}` intact — **masks survive the sandbox `result.json`
  serialization boundary**. Docker mode uses the identical `run_inference` path;
  the live docker probe (`test_sandbox_runtime.py`, T023) exercises it on a
  Docker host with `HARNESS_TEST_SEG_WEIGHTS` set.

## Notes / follow-ups

- The `miou` threshold ships **unratified** (`thresholds.yaml`
  `segmentation.capability`/`domain_stress`, `ratified: false`), so every
  segmentation run routes to `pending_adjudication` until governance ratifies a
  value (FR-207) — the build ships the slot + fail-safe routing, not the number.
- A real-road-scene mIoU (fetched Open Images `-seg` slice) and the docker-mode
  live probe are the remaining optional [HW] steps; the offline pipeline + the
  real-checkpoint adapter/sandbox path are validated above.
