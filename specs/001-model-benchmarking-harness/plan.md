# Implementation Plan: Model Benchmarking Harness (POC)

**Branch**: `001-model-benchmarking-harness` | **Date**: 2026-07-10 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/001-model-benchmarking-harness/spec.md`

**Constitution**: v1.0.0 (`.specify/memory/constitution.md`)

## Summary

A web-based benchmarking harness that gates computer-vision models through a three-tier evaluation (capability → local-context stress → operational/safety), with a mandatory single-reviewer adjudication gate and auto-generated Model Cards. Models are submitted as serialized weights + a declared framework and executed in a **no-network Docker sandbox** via per-framework inference adapters. The Tier 1 benchmark is chosen from a **model-class registry** (POC demonstrates object detection + image classification end-to-end); Tier 2 uses a **permissively licensed public stand-in** dataset plus permissive corruption transforms, so the repository stays code-only and license-clean.

## Technical Context

**Language/Version**: Python 3.11 (backend + evaluation engine); TypeScript 5 / React 18 (frontend).

**Primary Dependencies**:
- API: **FastAPI** + Uvicorn.
- Async execution: **RQ + Redis** (lightweight job queue; Celery considered — see research).
- Sandbox: **Docker** via `docker` (docker-py) SDK — ephemeral containers, `--network none`, resource caps.
- ML/eval: **PyTorch**, **ONNX Runtime**, **Ultralytics** (detection), **timm** (classification), **torchmetrics** + **pycocotools** (metrics), **pytorch-grad-cam** (visual grounding).
- Perturbations: **imagecorruptions** (Apache-2.0) + **albumentations** (MIT) applied to owned/permissive data.
- Persistence: **SQLite** + **SQLModel/SQLAlchemy** (metadata); filesystem for artifacts.
- Frontend: **React + Vite + TypeScript**.
- Datasets: **FiftyOne** (Open Images permissive subset) + shell fetch scripts.
- Cards: **Jinja2** markdown templates.

**Storage**: SQLite for metadata (append-only enforced at the service layer for runs/audit); filesystem (gitignored `data/`, `models/`, `results/`) for weights, results, and generated cards. Only `samples/` (owned/permissive) is committed.

**Testing**: **pytest** (contract/integration/unit) backend; **Vitest + React Testing Library** frontend. Gating logic is test-first (Constitution VI).

**Target Platform**: Linux containers (Docker required for the sandbox); developed on Windows via WSL2.

**Project Type**: Web application (frontend + backend) with a reusable evaluation-engine package.

**Performance Goals**: POC / single-node. Correctness and reproducibility over throughput. Concurrency: one active sandboxed run at a time is acceptable for the POC.

**Constraints**: every run isolated with no network egress; repository never contains third-party datasets or weights; run and audit records are append-only.

**Scale/Scope**: a handful of submitted models; 2 demonstrated classes; ≤1k-image stand-in test sets; single reviewer.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.* — Derived from Constitution v1.0.0. Principles I and II admit no justification.

- [x] **I. Human-in-the-Loop (NON-NEGOTIABLE)** — the `ModelVersion` state machine has no transition to `approved` from a flagged run except through an `AdjudicationRecord`; the "approve" transition requires a decision row (reviewer + rationale + timestamp). Enforced in the service layer and covered by a test that asserts no auto-approval path exists.
- [x] **II. Licensing-Clean (NON-NEGOTIABLE)** — no dataset/weights committed (`.gitignore` blocks `data/ models/ *.pt *.pth *.onnx`); datasets obtained by `scripts/fetch_*`; perturbations via Apache/MIT libraries on permissive/owned data; only `samples/` committed. A CI-style test scans the tree for restricted-data signatures.
- [x] **III. Model-Class-Appropriate** — `BenchmarkRegistry` maps class → benchmark + metric; Tier 1 refuses a class with no registered benchmark; Tier 2 scoring emits per-class metrics for safety-critical classes.
- [x] **IV. Reproducibility & Contamination** — pinned deps + seeded runs; `GoldenTestSet.checksum` stamped on every `TierResult`; sets never public; Docker `--network none` + ephemeral + read-only mounts; `EvaluationRun`/`AuditEvent` append-only.
- [x] **V. Verify-First, No Fabrication** — Model Card generator emits `to be confirmed` for any absent field; every `TierResult` stores its evidence ref + dataset checksum; `approved` requires a complete, queryable lineage.
- [x] **VI. Test-First** — verdict logic, threshold checks, the adjudication transition, and the licensing guard get failing tests before implementation.

**Result: PASS.** No violations → Complexity Tracking empty.

## Project Structure

### Documentation (this feature)

```text
specs/001-model-benchmarking-harness/
├── spec.md              # feature spec (input)
├── plan.md              # this file
├── research.md          # Phase 0 — decisions + rationale + alternatives
├── data-model.md        # Phase 1 — entities, relationships, state machine
├── contracts/           # Phase 1 — REST API + inference-adapter interface
│   ├── openapi.yaml
│   └── inference-adapter.md
├── quickstart.md        # Phase 1 — runnable end-to-end validation
└── checklists/
    └── requirements.md
```

### Source Code (repository root)

```text
backend/
├── app/                 # FastAPI: routers, schemas, dependency wiring
│   ├── api/             # endpoint handlers (models, runs, golden-sets, adjudication)
│   ├── db/              # SQLModel models + append-only repositories
│   └── services/        # orchestration, verdict, adjudication, card generation
├── engine/              # reusable evaluation engine (framework-agnostic)
│   ├── registry/        # model-class → benchmark/metric registry
│   ├── adapters/        # per-framework inference adapters (pytorch, onnx)
│   ├── tiers/           # tier1_capability, tier2_stress, tier3_ops
│   ├── perturb/         # permissive corruption transforms (rain/low-light/fog)
│   ├── metrics/         # mAP, top-k, mIoU, per-class recall
│   ├── sandbox/         # Docker no-egress runner
│   └── cards/           # Model Card generator (Jinja2)
├── worker/              # RQ worker entrypoint
└── tests/               # contract/ integration/ unit/

frontend/
├── src/
│   ├── pages/           # Submit, ModelDetail, AdjudicationQueue, Review
│   ├── components/
│   └── api/             # typed client
└── tests/

scripts/                 # fetch_open_images.py, seed_demo.py  (NO data committed)
samples/                 # owned/permissive sample images ONLY
```

**Structure Decision**: Web application (frontend + backend) with the evaluation logic isolated in `backend/engine/` as a framework-agnostic package. This keeps the gating logic independently testable (Constitution VI), lets the sandbox runner wrap the engine unchanged, and allows a future CLI or API-only deployment to reuse `engine/` without the web layer.

## Phase 0 — Research

See [research.md](./research.md). All Technical Context choices are resolved (no remaining `NEEDS CLARIFICATION`); deferred items from clarify (threshold values, tolerance number, Tier-3 method depth, hosting) are recorded as decisions with POC defaults + follow-ups.

## Phase 1 — Design & Contracts

- [data-model.md](./data-model.md) — 8 core entities + enums + the `ModelVersion` state machine.
- [contracts/openapi.yaml](./contracts/openapi.yaml) — REST endpoints for submit / status / history / golden-set registration / adjudication.
- [contracts/inference-adapter.md](./contracts/inference-adapter.md) — the per-framework adapter interface the engine depends on.
- [quickstart.md](./quickstart.md) — runnable end-to-end validation (fetch permissive sample → seed a demo model → evaluate → adjudicate → read card).

## Post-Design Constitution Re-Check

Re-evaluated after Phase 1: the data model encodes the no-auto-approval state machine (I), the contracts expose an adjudication decision endpoint but no direct force-approve (I), the fetch-script + `samples/`-only design holds (II), the registry and per-class metrics are first-class entities (III), checksum/append-only/isolation are in the schema (IV/V), and contract tests are specified before implementation (VI). **Result: PASS — no new violations, Complexity Tracking remains empty.**

## Complexity Tracking

No constitution violations. Table intentionally empty.
