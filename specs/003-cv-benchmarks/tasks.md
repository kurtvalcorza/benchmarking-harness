---
description: "Tasks for the computer-vision capability benchmarks (post-002 increments + image segmentation)"
---

# Tasks: Computer-Vision Capability Benchmarks

**Input**: `specs/003-cv-benchmarks/spec.md`

**Prerequisites**: `spec.md` (this feature); `plan.md`, `research.md`, `data-model.md`, `contracts/` to be authored before US4 implementation.

**Tests**: Mandatory. Constitution VI / FR-209 require the segmentation coverage, scorer, and adapter tests to be written and observed failing before implementation.

**Format**: `[ID] [P?] [Story] Description with exact file paths`. `[x]` = delivered; `[ ]` = to build.

## Phase R — Retroactive record (delivered since feature 002; NOT re-implemented)

These are captured for traceability; each is already merged or in review.

- [x] T001 [US1] Stop the profile-gated `runner` secret from breaking the default `docker compose up` — `${HARNESS_RUNNER_TOKEN:-}` + runner lifespan fail-fast in `docker-compose.yml`, `backend/runner/main.py` (PR #9 `765a929`)
- [x] T002 [US2] Object-scoped, role-gated `GET /models` + `ModelListItemOut` in `backend/app/api/models.py`, `backend/app/api/schemas.py`; contract in `openapi.yaml` + `security-boundary.md` (PR #10 `9647d75`)
- [x] T003 [US2] Frontend Models/history page + nav + `client.listModels()` surfacing status, verdict, gated metric, and infra-failure reason — `frontend/src/pages/ModelsList.tsx`, `main.tsx`, `api/client.ts` (PR #10 `9647d75`)
- [~] T004 [US3] PyTorch adapter loads Ultralytics YOLO classification checkpoints (try `YOLO()` first, fall back to `torch.load`; `is_yolo`; `_predict_cls` YOLO `.probs` path; clear state_dict rejection; fail loud on empty class names) in `backend/engine/adapters/pytorch_adapter.py` + unit tests — **PR #11, IN REVIEW; must merge to `main` before US4 implementation so this branch inherits the loader**

## Phase 0 — Design for US4 (before code) — ✅ DONE (this artifact set)

- [x] T010 [US4] `plan.md` + `research.md`: data source = Open Images V7 `-seg` (CC-BY, R2), mIoU = dataset-wide per-class pixel IoU (R1), mask representation = COCO RLE via pycocotools (R3), deterministic instance→semantic reduction (R4)
- [x] T011 [US4] `data-model.md` + `contracts/{segmentation-metric,inference-adapter}.md`: the `Prediction.mask` channel, segmentation annotation shape, per-class IoU floors, and content-addressed mask evidence
- [x] T012 [US4] `quickstart.md` + `checklists/requirements.md` (Spec Kit parity with 002)

## Phase 1 — Tests first (US4, observed failing before impl — FR-209)

- [x] T020 [P] [US4] Mask coverage + mIoU unit tests (perfect/partial/missing; per-class IoU; reference agreement; reduction determinism; malformed/dim-mismatch coverage) in `backend/tests/unit/test_segmentation_miou.py`
- [x] T021 [P] [US4] Adapter shape-dispatch test: non-`-seg`/bare checkpoint under segmentation rejected clearly (`importorskip`; the real `-seg` load runs live) in `backend/tests/unit/test_pytorch_adapter.py`
- [x] T022 [P] [US4] Integration: a segmentation submission scores mIoU end-to-end (stub-seg model + sample mask golden set) + registration masks/IoU-floors in `backend/tests/integration/test_segmentation_eval.py`
- [x] T023 [US4] Live sandbox segmentation-runtime probe (real `yolov8n-seg.pt` on a docker host) in `backend/tests/integration/test_sandbox_runtime.py`

## Phase 2 — Prediction + scorer (US4)

- [x] T030 [US4] Add the mask channel to `Prediction` (+ `to_dict`/`from_dict`) in `backend/engine/adapters/base.py` (FR-201)
- [x] T030a [US4] Preserve the mask channel through `engine/metrics/__init__.py::canonicalize()` (remaps each instance label, never drops the masks) (FR-215)
- [x] T030b [US4] Deterministic instance→semantic reduction (same-class union, cross-class overlap by confidence, fixed `(score desc, index asc)` ordering) in `engine/metrics/segmentation.py::reduce_instances_to_semantic` (FR-217)
- [x] T031 [US4] `engine/metrics/segmentation.py`: `evaluate_segmentation()` → `miou` + per-class IoU with complete-coverage accounting (dataset-wide pixel ∩/∪) (FR-202)
- [x] T032 [US4] Dispatch `segmentation` in `engine/metrics/__init__.py::evaluate()` (removed `NotImplementedError`) (FR-203)
- [x] T032a [US4] Added `segmentation` to `engine.metrics.SCORED_CLASSES`; the `app/api/models.py` guard now accepts it (FR-213)
- [x] T033 [US4] Coverage + evaluator provenance for masks (`segmentation-miou` evaluator, coverage accounting) in `engine/metrics/coverage.py` / scorer (FR-208)
- [x] T033a [US4] Typed validation of malformed mask payloads (`malformed_rle`/`mask_dim_mismatch`/`mask_out_of_range`) in the coverage layer (FR-216)
- [x] T033b [US4] Persist reduced per-class masks as content-addressed evidence (`_write_content_addressed`; `segmentation_evidence` on the tier) so mask evidence is resolvable + reproducible (FR-218)

## Phase 3 — Adapter (US4)

- [x] T040 [US4] PyTorch adapter segmentation branch: load Ultralytics `-seg` via `YOLO()` (task `segment`), emit per-instance RLE masks (retina_masks); reject non-seg checkpoints clearly in `backend/engine/adapters/pytorch_adapter.py` (FR-204)
- [x] T041 [US4] Stub adapter segmentation predictions (deterministic hash-seeded masks from GT) for the offline/test path in `backend/engine/adapters/stub_adapter.py`

## Phase 4 — Data, registry, thresholds (US4)

- [x] T050 [US4] `scripts/fetch_open_images.py`: fetch a permissive Open Images `-seg` slice (instance masks → RLE) into gitignored `data/`; owned synthetic sample generated under `samples/` by `scripts/gen_samples.py` (FR-205)
- [x] T051 [US4] Golden-set registration accepts segmentation mask annotations + per-class IoU floors (`iou_floors` in the manifest; stored in the generic floor column) (FR-206)
- [x] T051a [US4] Generalized the Tier-2 per-class safety-floor path from recall-only to metric-typed: `safety_critical_floors` reads `per_class_iou` for segmentation; the flag trigger (`safety_critical_iou_below_floor` via `FlagInput.safety_metric`) + the Model Card safety table are metric-typed (FR-214)
- [x] T051b [US4] Golden-set registration REJECTS a mask-less dataset as segmentation (`validate_dataset(require_masks=True)`) so a detection/classification-shaped dataset cannot register as segmentation (FR-219)
- [x] T052 [US4] `backend/thresholds.yaml`: `segmentation.capability`/`domain_stress` `miou` thresholds (`ratified: false` until governance) (FR-207)
- [x] T053 [US4] Model Card surfaces `miou` (tier table) + per-class IoU (metric-typed safety table) (FR-210)

## Phase 5 — Validation (US4)

- [x] T060 [US4] Full backend suite (**229 passed, 2 skipped**) + constitution gates green; no detection/classification regression (FR-212)
- [x] T061 [US4] Live: real `yolov8n-seg.pt` loads (task=segment), emits 96×96 RLE masks, scores mIoU + survives the sandbox serialization boundary; recorded in `specs/003-cv-benchmarks/validation.md`
- [ ] T062 [US4] Dual-bot review loop → merge
