# Feature Specification: Computer-Vision Capability Benchmarks

**Feature Branch**: `003-cv-benchmarks`

**Created**: 2026-07-12

**Status**: Draft (for review)

**Input**: User description: "For computer vision models, we need benchmarks for Image Classification, Object Detection, and Image Segmentation." Plus: retroactively capture, in this spec, the increments shipped since feature 002, marked as done.

**Constitution**: governed by v1.0.0 (`.specify/memory/constitution.md`). Principles I (Human-in-the-Loop) and II (Licensing-Clean) remain non-negotiable; Tier-1 capability is "the standard benchmark for the model's class" (Principle III / registry).

## Purpose and scope

This feature closes out the three **core computer-vision capability benchmarks** so that a model of each class is gated on its standard, class-appropriate metric:

| Model class | Standard benchmark (Tier-1 metric) | State at spec time |
|---|---|---|
| Object detection | COCO mAP — `coco_ap_50_95` | **Shipped** (feature 002 / US2) |
| Image classification | ImageNet top-1 — `top1` | Scorer shipped (002); **loader completed** by US3 below |
| Image segmentation | Cityscapes mIoU — `miou` | **Registry slot only; no scorer, adapter, or data** → US4 (new) |

It is deliberately a mixed spec:

- **Retroactive stories (US1–US3)** document the increments delivered **since feature 002 merged** — already merged or in review — so the spec record is not silently behind the code. They are marked **DONE** with their delivering PR/commit and are not re-implemented.
- **The new story (US4)** specifies **image segmentation**, the one remaining core CV modality, as the work to build.

Pose / lane / face remain registered-but-unratified slots and are **out of scope** here (Principle III allows a class to exist without a ratified threshold — such runs land in `pending_adjudication`).

## Clarifications

### Session 2026-07-12

- Q: Is this greenfield or continuation? -> A: **Continuation** of the feature-001 harness and feature-002 hardening. No constitution change; the registry/tiers/adapters extend by adding entries, not by re-architecting (FR-020/025).
- Q: What is the segmentation reference benchmark and metric? -> A: **Semantic-segmentation mean IoU (mIoU)** over the registered class set, standing in for Cityscapes mIoU. Per-class IoU is reported; the safety-critical per-class recall floor concept from detection has its mIoU analogue (per-class IoU floors) available but unratified for the POC.
- Q: What model format is the classification/segmentation reference? -> A: **Ultralytics YOLO** classification (`-cls`) and segmentation (`-seg`) checkpoints are first-class, alongside the existing timm/torchvision and ONNX paths. This mirrors the detection path already using Ultralytics YOLO.
- Q: Where does segmentation ground truth come from and under what license? -> A: A **fetched, permissively licensed** segmentation slice (mask/polygon annotations) written to the gitignored `data/` by `scripts/`, never committed (Constitution II). An owned synthetic sample stands in for the offline demo.
- Q: How are masks represented in evidence? -> A: As **run-length-encoded (RLE) or polygon masks** in the dataset annotations and in predictions, digested into the existing content-addressed evidence store (SC-004 reproducibility). No raw image pixels are embedded.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Default stack starts without over-required secrets (Priority: P2) — ✅ DONE

An operator runs the documented `docker compose up -d` for the dev stack and it starts, without being forced to set a production-only secret for a service that is not even started.

**Why this priority**: A documented first-run command that fails out of the box blocks every new user; it is not a safety gap, hence P2.

**Independent Test**: With `HARNESS_RUNNER_TOKEN` unset, `docker compose config`/`up` for the default profile succeed and exclude the `runner`; with it set under the `production` profile, the runner receives it and still fails closed at boot when it is empty.

**Acceptance Scenarios**:

1. **Given** `HARNESS_RUNNER_TOKEN` is unset, **When** the operator runs the default `docker compose up -d`, **Then** the stack starts (api, worker, redis, sandbox image) and the profile-gated `runner`/`postgres` are excluded.
2. **Given** the `production` profile and an unset token, **When** the runner container starts, **Then** it refuses to boot (a visible crash, not a healthy container that silently 503s every `/run`).

**Delivered by**: PR #9 (`765a929`) — compose `${HARNESS_RUNNER_TOKEN:-}` + runner lifespan fail-fast.

---

### User Story 2 — Operators can browse evaluation history and why a run didn't evaluate (Priority: P2) — ✅ DONE

An operator sees a list of every model submission they are authorized to view, with its latest verdict and gated metric, and — when a model could not be evaluated — the reason, instead of a submission silently stuck at `pending`.

**Why this priority**: Governance oversight and debugging both need a history surface; the harness previously exposed only Submit, a flagged-only queue, and per-model detail by URL. P2 (no safety gate is bypassed).

**Independent Test**: With submissions in mixed states (approved, rejected, flagged, infra-failed), `GET /models` returns each with status, latest verdict, gated metric, and an infra-failure reason; object scope holds (auditor all, submitter own, adjudicator flagged, governance denied).

**Acceptance Scenarios**:

1. **Given** several evaluated and one load-failed submission, **When** the operator opens Models, **Then** each row shows status + verdict + gated metric, and the load-failed one shows its infra-failure reason.
2. **Given** a governance-only token, **When** it calls `GET /models`, **Then** it is denied `403` (matching the authorization matrix), not handed an empty list.

**Delivered by**: PR #10 (`9647d75`) — `GET /models` (object-scoped, role-gated) + `ModelListItem` + frontend Models page.

---

### User Story 3 — Ultralytics YOLO classification models can be evaluated (Priority: P1) — ✅ DONE

A submitter uploads an Ultralytics YOLO **classification** checkpoint (`yolov8n-cls.pt`) as a `classification`/`pytorch` model, and it loads and runs through the tiers rather than infra-failing.

**Why this priority**: The classification benchmark cannot be exercised on the most common real classification checkpoint format if the adapter cannot load it; P1 because it blocks a core benchmark.

**Independent Test**: The adapter's shape dispatch classifies an Ultralytics checkpoint vs a timm module vs a bare state_dict; live on the sandbox, an Ultralytics `-cls` checkpoint loads as `task=classify` and predicts class probabilities.

**Acceptance Scenarios**:

1. **Given** an Ultralytics `-cls` checkpoint, **When** the adapter loads it, **Then** it is loaded via `YOLO()` (task must be `classify`) and prediction emits a top-1 label + class-score vector (so `canonicalize()`/top-5 work).
2. **Given** a fully-pickled timm/torchvision module, **When** the adapter loads it, **Then** the existing module path is used unchanged.
3. **Given** a bare state_dict (no architecture), **When** the adapter loads it, **Then** it fails with a clear, actionable message rather than an opaque `'dict' has no attribute 'eval'`.

**Delivered by**: PR #11 (`feat/ultralytics-classification`) — adapter checkpoint dispatch + `is_yolo` + `_predict_cls` YOLO path.

---

### User Story 4 — Image segmentation models are benchmarked with mIoU (Priority: P1) — ⬜ TODO

A submitter uploads an image-segmentation model and it is gated on the standard segmentation capability metric — **mean IoU** over the registered class set — with per-class IoU reported, complete coverage accounting, and reproducible mask evidence, exactly as detection and classification are gated on their standard metrics.

**Why this priority**: Segmentation is one of the three core CV tasks the harness claims to cover; today its registry slot exists but any segmentation run raises `NotImplementedError` and infra-fails. P1 — a claimed benchmark that cannot run.

**Independent Test**: Score deliberately incomplete, duplicate, extra, and valid segmentation prediction sets against a mask golden set; verify mIoU and per-class IoU match a reference computation on valid fixtures, that missing/duplicate/extra predictions produce typed coverage errors and cannot inflate the score, and that an Ultralytics `-seg` checkpoint loads and predicts masks live on the sandbox.

**Acceptance Scenarios**:

1. **Given** a segmentation golden set with a mask for every image, **When** a model omits or duplicates a prediction, **Then** coverage records it and it counts against the score (never silently favorable) — the US2/002 accounting rule extended to masks.
2. **Given** a valid segmentation prediction set, **When** the capability metric is computed, **Then** `miou` (mean over per-class IoU) and per-class IoU are produced and agree with a reference computation within tolerance.
3. **Given** an Ultralytics `-seg` checkpoint (`yolov8n-seg.pt`), **When** the adapter loads it, **Then** it loads via `YOLO()` (task must be `segment`) and predictions carry per-instance/per-class masks; a non-seg checkpoint under the segmentation class is rejected clearly.
4. **Given** a segmentation run and a ratified `miou` capability threshold, **When** mIoU is below the minimum, **Then** the model is rejected at capability (parallel to detection); with an unratified threshold it routes to `pending_adjudication` (FR-012b), never a silent pass.
5. **Given** a scored segmentation tier result, **When** it is persisted, **Then** it carries prediction coverage counts + evaluator provenance + dataset checksum (US2 evidence rules) and its mask evidence is content-addressed and reproducible (SC-004).

---

## Requirements *(mandatory)*

### Retroactive (already delivered — recorded for traceability, not re-implemented)

- **FR-101** (US1) ✅ The profile-gated `runner` MUST NOT make the default `docker compose up` fail; the runner secret is enforced by the runner service at boot, not by a required compose variable. *(PR #9)*
- **FR-102** (US2) ✅ The API MUST expose an object-scoped, role-gated `GET /models` list; each item MUST carry status, latest verdict, the gated capability metric, and an infra-failure reason when a run could not evaluate the model. *(PR #10)*
- **FR-103** (US2) ✅ The frontend MUST present a Models/history view surfacing the above, including the infra-failure reason. *(PR #10)*
- **FR-104** (US3) ✅ The PyTorch adapter MUST load an Ultralytics YOLO classification checkpoint (via `YOLO()`, task `classify`) and a fully-pickled timm/torchvision module, and MUST reject a bare state_dict with a clear message. *(PR #11)*

### New — Image segmentation (US4)

- **FR-201** The `Prediction` contract MUST carry a segmentation mask channel (per-image class masks and/or per-instance masks with labels), digestible into the evidence store; existing detection/classification fields are unchanged.
- **FR-202** A `segmentation` scorer MUST produce `miou` (mean of per-class IoU over the registered class set) and per-class IoU, with the same complete-coverage accounting as classification/detection (missing = counted against; duplicate/extra = typed error; the denominator is the registered dataset).
- **FR-203** `engine.metrics.evaluate()` MUST dispatch `segmentation` to that scorer (no longer `NotImplementedError`).
- **FR-204** The PyTorch (and, where feasible, ONNX) adapter MUST load an Ultralytics YOLO `-seg` checkpoint (via `YOLO()`, task `segment`) and emit mask predictions; a checkpoint whose task is not `segment` under the segmentation class MUST be rejected clearly.
- **FR-205** A segmentation benchmark dataset MUST be fetchable by `scripts/` under a permissive license into gitignored `data/` (mask/polygon annotations + a manifest `label_map`), with an owned synthetic sample for the offline demo; no dataset is committed (Constitution II).
- **FR-206** A segmentation Golden Test Set MUST be registrable (mask annotations, checksum, conditions, optional per-class IoU floors) and selected as the class benchmark like detection's.
- **FR-207** A capability (and domain-stress) `miou` threshold MUST exist in `thresholds.yaml`; until governance ratifies it (`ratified: true`), a segmentation run routes to `pending_adjudication`, never a silent pass (FR-012b).
- **FR-208** Segmentation tier results MUST carry prediction coverage + evaluator provenance + dataset checksum (US2 evidence rules); mask evidence MUST be content-addressed and reproducible (SC-004).
- **FR-209** Tests MUST be written first and observed failing (Constitution VI): the mask coverage/scoring unit tests, the adapter shape-dispatch tests, and a live sandbox segmentation-runtime probe.
- **FR-210** The Model Card MUST surface `miou` + per-class IoU for segmentation (the card already reserves the `miou` key).

### Non-functional / invariants (unchanged, must hold)

- **FR-211** No-egress sandbox, append-only history, human adjudication gate, and licensing-cleanliness are unchanged for the new modality (Constitution I/II/IV).
- **FR-212** The new modality MUST NOT regress detection or classification; the full backend suite + gates stay green.

## Delivery status

| Story | Priority | Status | Delivered / target |
|---|---|---|---|
| US1 compose default-up fix | P2 | ✅ Done | PR #9 `765a929` |
| US2 models list / history view | P2 | ✅ Done | PR #10 `9647d75` |
| US3 Ultralytics YOLO classification loader | P1 | ✅ Done (in review) | PR #11 |
| US4 image segmentation benchmark (mIoU) | P1 | ⬜ To build | this feature |

## Out of scope

- Pose, lane, and face benchmarks (registered slots; unratified — remain `pending_adjudication`).
- Panoptic/instance-AP segmentation metrics beyond semantic mIoU (mIoU is the POC standard; instance mask-AP is a follow-up).
- Vision-language / document benchmarks (spec-excluded for the POC).
- Ratifying the numeric `miou` threshold (governance action; the spec requires the slot + fail-safe routing, not the ratified value).

## Assumptions

- Ultralytics remains the reference multi-task loader (detection/classification/segmentation), already baked into the sandbox image.
- A permissively licensed segmentation slice with masks is fetchable (e.g. an Open Images / COCO-style segmentation subset under its own terms) — exact source finalized in `plan.md`/`research.md` at implementation.
- CI continues to install `[dev]` (no ml extra); ml-dependent paths are validated live on the sandbox image, as with detection (F9) and classification (US3).
