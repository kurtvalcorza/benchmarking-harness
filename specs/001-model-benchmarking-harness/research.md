# Phase 0 — Research

Decisions resolving the Technical Context and the clarify-deferred items. Each: **Decision / Rationale / Alternatives considered**.

## R1 — Backend framework: FastAPI

- **Decision**: FastAPI + Uvicorn.
- **Rationale**: async-friendly for launching/polling sandboxed jobs; Pydantic schemas double as the API contract; minimal boilerplate for a POC; strong typing aligns with the frontend's typed client.
- **Alternatives**: Django (heavier; ORM+admin not needed here); Flask (less native async / validation).

## R2 — Async execution: RQ + Redis

- **Decision**: RQ (Redis Queue) with a single worker for the POC.
- **Rationale**: an evaluation run is long and must not block the API; RQ is minimal, easy to reason about, and one worker satisfies the "one active sandboxed run at a time" POC constraint.
- **Alternatives**: Celery (more features, more config — overkill for a POC); FastAPI BackgroundTasks (dies with the process, no durable queue/retry); Dramatiq (fine, less ubiquitous).

## R3 — Sandbox isolation: Docker, no network

- **Decision**: run each evaluation in an ephemeral Docker container started with `--network none`, read-only model/data mounts, CPU/memory/time caps, auto-removed after the run.
- **Rationale**: directly satisfies Constitution IV (no egress, isolated, ephemeral) and treats model code as untrusted. Docker is ubiquitous and already used by the wider stack.
- **Alternatives**: gVisor / Firecracker microVMs (stronger isolation, heavy for a POC); subprocess with seccomp (weaker, easy to get wrong); no sandbox (violates Constitution IV — rejected).

## R4 — Model execution: per-framework inference adapters

- **Decision**: a small `InferenceAdapter` interface (`load`, `predict`, `describe`) with concrete PyTorch and ONNX Runtime implementations; the submitter declares framework + class.
- **Rationale**: keeps the engine framework-agnostic (Constitution III's class-keying + open extension); ONNX covers cross-framework models, PyTorch covers the common CV case (Ultralytics/timm).
- **Alternatives**: container-per-model bundling runtime (heaviest; deferred as a future option); single-framework only (fails the "all classes supported" clarify answer).

## R5 — Benchmark registry & metrics

- **Decision**: a declarative `BenchmarkRegistry` mapping model class → (benchmark dataset id, metric fn). Metrics: detection → mAP@50/50–95 + per-class recall (pycocotools/torchmetrics); classification → top-1/top-5 + macro-F1; segmentation → mIoU; pose → OKS AP; lane → F1; face → NME. POC wires detection + classification; others registered.
- **Rationale**: encodes Constitution III as data, not code branches; adding a class = a registry entry + a metric fn.
- **Alternatives**: hardcoded per-class conditionals (brittle, violates the "slot" design); a single universal metric (impossible across tasks).

## R6 — Adverse-condition perturbations (license-clean)

- **Decision**: generate rain / low-light / fog (and clean baseline) with `imagecorruptions` (Apache-2.0) and `albumentations` (MIT), applied at run time to owned/permissive images. Each condition scored separately; worst-case drop reported.
- **Rationale**: satisfies Constitution II — the perturbation *method* is permissive code applied to permissive data, so no restricted dataset (AODRaw/ACDC/ImageNet-C data) is ever redistributed. Reproduces the ImageNet-C-style degradation curve.
- **Alternatives**: shipping AODRaw/ACDC images (redistribution barred; non-commercial — rejected); real captured adverse data (owned-data sourcing, out of POC scope).

## R7 — Persistence: SQLite + filesystem

- **Decision**: SQLite (via SQLModel) for metadata; filesystem for weights/results/cards under gitignored dirs. Append-only enforced in repositories (no update/delete on `EvaluationRun`, `TierResult`, `AuditEvent`).
- **Rationale**: zero-infra for a POC; append-only at the service layer satisfies Constitution IV/V; Postgres is a drop-in later via SQLAlchemy.
- **Alternatives**: Postgres now (infra overhead for a POC); event-store DB (premature).

## R8 — Frontend: React + Vite + TypeScript

- **Decision**: React + Vite + TS with three surfaces: Submit, Model Detail (status/results/card), Adjudication Queue + Review.
- **Rationale**: matches the ecosystem and the clarify answer (web app + single-reviewer UI); Vite is fast for a POC; typed client mirrors FastAPI schemas.
- **Alternatives**: server-rendered HTMX (leaner, but the reviewer UI benefits from interactivity); no UI / CLI (contradicts the clarify decision).

## R9 — Dataset acquisition (stand-in): FiftyOne / Open Images

- **Decision**: `scripts/fetch_open_images.py` pulls a small permissive Open Images subset (CC BY) for detection + a permissive classification subset; nothing is committed. A tiny owned `samples/` set ships for smoke tests.
- **Rationale**: license-clean stand-in per the clarify answer; FiftyOne makes Open Images subsetting easy; unblocks the POC without owned-data sourcing/legal.
- **Alternatives**: ImageNet/COCO (redistribution/non-commercial issues — fetched-not-committed only, and heavier); synthetic-only (less realistic).

## R10 — Deferred-item POC defaults (from clarify)

- **Thresholds (OQ-3)**: provisional values in a `thresholds.yaml` config; an unset/unratified threshold yields `pending-adjudication`, never `pass` (spec edge case). Follow-up: governance ratifies real values.
- **Reproducibility tolerance (SC-004)**: POC default — metric scores must match to 1e-6 for deterministic paths; for any nondeterministic op, a documented ε per metric. Follow-up: calibrate from first-run data.
- **Tier 3 method depth**: POC implements visual grounding via Grad-CAM region-overlap and resource profiling via wall-clock latency + throughput + param/memory count. **Robustness (data-drift/shortcut) is de-scoped for the POC** (analyze remediation C2) and moved to Out of Scope; adversarial/drift batteries are future work.
- **Hosting (OQ-5)**: single-node Docker host for the POC; the web app + worker + Redis run via `docker compose`. Follow-up: sovereign/on-prem hosting decision.

All `NEEDS CLARIFICATION` from Technical Context are resolved. No blocking unknowns remain for Phase 1.
