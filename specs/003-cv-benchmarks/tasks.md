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
- [x] T004 [US3] PyTorch adapter loads Ultralytics YOLO classification checkpoints (dispatch on checkpoint shape; `is_yolo`; `_predict_cls` YOLO `.probs` path; clear state_dict rejection) in `backend/engine/adapters/pytorch_adapter.py` + unit tests (PR #11)

## Phase 0 — Design for US4 (before code)

- [ ] T010 [US4] `plan.md` + `research.md`: choose the permissively licensed segmentation data source (masks), the mIoU definition (semantic, per-class + mean), and the mask representation (RLE/polygon) — Constitution II/licensing recorded
- [ ] T011 [US4] `data-model.md` + `contracts/inference-adapter.md` delta: the mask channel on `Prediction`, the segmentation annotation shape, and the `SegmentationEvidence`/coverage record

## Phase 1 — Tests first (US4, observed failing before impl — FR-209)

- [ ] T020 [P] [US4] Mask coverage + mIoU unit tests (complete/incomplete/duplicate/extra/valid; per-class IoU; reference agreement) in `backend/tests/unit/test_segmentation_miou.py`
- [ ] T021 [P] [US4] Adapter shape-dispatch tests: Ultralytics `-seg` checkpoint vs non-seg-under-segmentation rejection (`importorskip` for the live load) in `backend/tests/unit/test_pytorch_adapter.py`
- [ ] T022 [P] [US4] Integration: a segmentation submission scores mIoU end-to-end (stub-seg model + sample mask golden set) in `backend/tests/integration/test_segmentation_eval.py`
- [ ] T023 [US4] Live sandbox segmentation-runtime probe (real `yolov8n-seg.pt` on a docker host) in `backend/tests/integration/test_sandbox_runtime.py`

## Phase 2 — Prediction + scorer (US4)

- [ ] T030 [US4] Add the mask channel to `Prediction` (+ `to_dict`/`from_dict`) in `backend/engine/adapters/base.py` (FR-201)
- [ ] T031 [US4] `engine/metrics/segmentation.py`: `evaluate_segmentation()` → `miou` + per-class IoU with complete-coverage accounting (FR-202)
- [ ] T032 [US4] Dispatch `segmentation` in `engine/metrics/__init__.py::evaluate()` (remove `NotImplementedError`) (FR-203)
- [ ] T033 [US4] Coverage + evaluator provenance for masks (US2 evidence rules) in `engine/metrics/coverage.py` / scorer (FR-208)

## Phase 3 — Adapter (US4)

- [ ] T040 [US4] PyTorch adapter segmentation branch: load Ultralytics `-seg` via `YOLO()` (task `segment`), emit mask predictions; reject non-seg checkpoints clearly in `backend/engine/adapters/pytorch_adapter.py` (FR-204)
- [ ] T041 [US4] Stub adapter segmentation predictions (deterministic masks from GT) for the offline/test path in `backend/engine/adapters/stub_adapter.py`

## Phase 4 — Data, registry, thresholds (US4)

- [ ] T050 [US4] `scripts/fetch_*`: fetch a permissive segmentation slice (masks) into gitignored `data/` + an owned synthetic sample under `samples/` (FR-205)
- [ ] T051 [US4] Golden-set registration accepts segmentation mask annotations + optional per-class IoU floors (FR-206)
- [ ] T052 [US4] `backend/thresholds.yaml`: `segmentation.capability`/`domain_stress` `miou` thresholds (unratified until governance) (FR-207)
- [ ] T053 [US4] Model Card surfaces `miou` + per-class IoU (FR-210)

## Phase 5 — Validation (US4)

- [ ] T060 [US4] Full backend suite + gates green; no detection/classification regression (FR-212)
- [ ] T061 [US4] Live: register a segmentation golden set + evaluate a real `yolov8n-seg.pt` end-to-end; record in `specs/003-cv-benchmarks/validation.md`
- [ ] T062 [US4] Dual-bot review loop → merge
