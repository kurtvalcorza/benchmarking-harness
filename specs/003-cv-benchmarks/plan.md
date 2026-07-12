# Implementation Plan: Computer-Vision Capability Benchmarks

**Branch**: `003-cv-benchmarks` | **Date**: 2026-07-12 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/003-cv-benchmarks/spec.md`

## Summary

Complete the three core computer-vision capability benchmarks. Detection (COCO mAP) and classification (ImageNet top-1) are delivered; this feature retro-records the post-002 increments (US1–US3) and builds the one remaining modality — **image segmentation**, gated on **semantic mean IoU (mIoU)** — reusing the existing tier/registry/adapter seams so the addition is data + a scorer + an adapter branch, not an engine re-architecture (FR-020/025).

## Technical Context

**Language/Version**: Python 3.11 (backend/engine), TypeScript/React (frontend — unchanged for US4).

**Primary Dependencies**: FastAPI, SQLModel, RQ; Ultralytics YOLO + torch (sandbox image) for `-seg` inference; **pycocotools** (already a core dep from US2) for RLE mask encode/decode and IoU via `pycocotools.mask`.

**Storage**: SQLite (dev/test) / PostgreSQL (prod). New: per-class IoU floors on the Golden Test Set; content-addressed mask evidence in the existing evidence store.

**Testing**: pytest (unit/integration/contract), test-first (FR-209). ml-dependent paths (`-seg` load) validated live on the sandbox image, as with detection (F9) and classification (US3); CI installs `[dev]` only.

**Target Platform**: Linux server; the no-egress Docker sandbox executes untrusted model code.

**Project Type**: Web service (backend + engine + worker + frontend).

**Performance Goals**: POC-scale — tens of images per golden set; nano `-seg` models run CPU in the sandbox in seconds.

**Constraints**: No-egress sandbox, append-only history, licensing-clean data, deterministic/reproducible scoring (SC-004).

**Scale/Scope**: One new modality end-to-end; no change to detection/classification behavior (FR-212).

## Constitution Check

- **I Human-in-the-loop** — an unratified `miou` threshold (or a per-class IoU-floor breach) routes to `pending_adjudication`; no segmentation model auto-approves below a gate (FR-207/214).
- **II Licensing-clean** — segmentation masks are fetched from a permissive source into gitignored `data/`, never committed; an owned synthetic sample ships for the offline demo (FR-205, R2).
- **III Benchmark-per-class** — segmentation already has a registry slot (`miou` / Cityscapes); this feature supplies the missing scorer + threshold so the slot is real (FR-202/203).
- **IV No-egress / append-only** — masks run through the same `--network none` sandbox; evidence and results stay append-only + content-addressed (FR-208/218).
- **V Verify-first** — coverage counts + evaluator provenance + dataset checksum travel with every segmentation result (FR-208).
- **VI Test-first** — scorer/adapter/coverage tests written and observed failing before implementation (FR-209).

No violation; no complexity deviation requested.

## Architecture

### Submission path
`segmentation` is added to `engine.metrics.SCORED_CLASSES`; the `app/api/models.py` guard accepts it so a segmentation upload is not `422`'d before evaluation (FR-213).

### Adapter / inference path
The PyTorch adapter gains a `segmentation` branch that loads an Ultralytics `-seg` checkpoint via `YOLO()` (task must be `segment`, mirroring the detection/classification YOLO-first pattern) and emits **per-instance masks** (class, confidence, mask) in a new `Prediction.mask` channel. A stub-seg path emits deterministic masks from ground truth for the offline/test path.

### Scoring path
`engine/metrics/segmentation.py::evaluate_segmentation()` (a) reduces per-instance masks to a deterministic **per-class semantic mask** (R4), (b) accumulates per-class intersection/union pixels over the registered dataset (missing prediction = empty mask, counted), (c) returns `miou` + per-class IoU. `canonicalize()` is extended to carry the mask channel through the label_map remap (FR-215). The coverage layer validates mask payloads (RLE/polygon/dims) as typed errors (FR-216).

### Gate / adjudication path
Tier-1 gates `miou` against `thresholds.yaml`; Tier-2 checks per-class **IoU** floors (generalized from recall floors), and the recall-named flag trigger + Model Card wording become metric-appropriate (FR-214). Unratified threshold → `pending_adjudication`.

### Evidence path
The reduced per-class masks are staged → digested → published content-addressed (RLE bytes), so a segmentation verdict's mask evidence is resolvable and reproducible (FR-218), reusing the US4/002 evidence store.

## Project Structure

### Documentation (this feature)
```
specs/003-cv-benchmarks/
  spec.md          # US1–US3 (retro, done) + US4 (segmentation)
  plan.md          # this file
  research.md      # R1–R9 design decisions (mask repr, data source, mIoU, reduction, …)
  data-model.md    # Prediction.mask, segmentation annotations, IoU floors, mask evidence
  contracts/
    segmentation-metric.md   # metric identity + mask validation + evidence shape
    inference-adapter.md     # delta: the mask channel + -seg load contract
  quickstart.md    # register a seg golden set + evaluate yolov8n-seg
  checklists/requirements.md
  tasks.md         # Phase R (retro) + Phase 0–5 (US4, test-first)
```

### Source Code (touched by US4)
```
backend/engine/adapters/base.py            # Prediction.mask channel (FR-201)
backend/engine/adapters/pytorch_adapter.py # -seg YOLO branch (FR-204)
backend/engine/adapters/stub_adapter.py    # deterministic stub masks
backend/engine/metrics/segmentation.py     # NEW: evaluate_segmentation → mIoU (FR-202)
backend/engine/metrics/__init__.py         # dispatch seg; SCORED_CLASSES; canonicalize masks (FR-203/213/215)
backend/engine/metrics/coverage.py         # malformed-mask validation (FR-216)
backend/engine/tiers/tier2_stress.py       # per-class IoU floors (FR-214)
backend/app/api/models.py                  # accept segmentation submissions (FR-213)
backend/app/services/…                      # IoU floors on golden set; mask evidence persistence (FR-214/218)
backend/thresholds.yaml                    # segmentation.miou thresholds (FR-207)
backend/engine/cards/generator.py          # surface miou + per-class IoU + IoU-breach wording (FR-210/214)
scripts/…                                   # fetch a permissive seg slice; owned synthetic sample (FR-205)
```

**Structure Decision**: Single web-service repo; segmentation slots into the existing engine seams — no new service or architecture.

## Delivery Phases

- **Phase 0** — plan/research/data-model/contracts (this set); settle mask representation + data source.
- **Phase 1** — tests first (mask coverage + mIoU, adapter dispatch, integration, live sandbox probe).
- **Phase 2** — `Prediction.mask` + `evaluate_segmentation` + `canonicalize` mask-preserve + dispatch/allowlist.
- **Phase 3** — adapter `-seg` branch + stub-seg.
- **Phase 4** — data fetch + golden-set registration (masks + IoU floors) + thresholds + card.
- **Phase 5** — validation (full suite + gates green; live `yolov8n-seg`); dual-bot review → merge.

## Complexity Tracking

No constitution deviation. The one genuinely new concept is the **mask channel + its deterministic instance→semantic reduction** (R4); everything else reuses detection/classification patterns (YOLO-first load, label_map canonicalize, coverage accounting, per-class floors, content-addressed evidence).
