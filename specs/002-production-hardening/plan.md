# Implementation Plan: Production Hardening and Evaluation Integrity

**Branch**: `002-production-hardening` | **Date**: 2026-07-11 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/002-production-hardening/spec.md`

## Summary

Harden the existing FastAPI/RQ/React benchmarking harness without changing its model-governance purpose. Add OIDC bearer-token validation and role authorization; bounded atomic artifact ingestion; complete prediction coverage validation and reference COCO detection metrics; atomic run/adjudication plus Model Card transactions; a PostgreSQL-backed transactional outbox with idempotent workers; evidence-based grounding; Alembic migrations; hardened isolated model execution; and locked/scanned dependencies. Preserve the offline SQLite/stub demo behind explicit development configuration and keep every Constitution gate green.

## Technical Context

**Language/Version**: Python 3.11; TypeScript 5.5+; Node.js 22 LTS

**Primary Dependencies**: FastAPI, SQLModel/SQLAlchemy, Alembic, PostgreSQL driver, PyJWT with cryptography, HTTPX (OIDC discovery/JWKS), Redis/RQ, pycocotools, React 18, React Router, standards-compliant browser OIDC client, Vite/Vitest supported releases

**Storage**: PostgreSQL in production; SQLite for tests/offline demo; local/bind-mounted artifact and evidence storage with atomic file finalization

**Testing**: pytest (unit/contract/integration/fault injection), Vitest + Testing Library, Ruff, ESLint, OpenAPI validation, migration upgrade tests, sandbox configuration/runtime probes, `pip-audit`, `npm audit`

**Target Platform**: Linux containers for production; Windows/macOS/Linux developer environments; Docker-compatible isolated runner

**Project Type**: Web application with API, background worker/dispatcher, evaluation sandbox, and React frontend

**Performance Goals**: authorization validation adds <=25 ms p95 with cached JWKS; upload memory remains O(chunk size); dispatch latency <=5 seconds in healthy operation; scoring overhead from coverage validation <=5% excluding reference metric calculation

**Constraints**: no restricted data committed; no model inference outside hardened sandbox; no flagged auto-approval; at-least-once delivery with exactly-once domain effect; 2 GiB default upload maximum; no fabricated grounding evidence

**Scale/Scope**: single production installation, up to 50 concurrent uploads, 20 workers, 100,000 model versions/runs, and multi-year append-only audit history; horizontal multi-region operation remains out of scope

## Constitution Check

*GATE: Passed before Phase 0 research. Re-check after Phase 1 design: passed.*

- [x] **I. Human-in-the-Loop (NON-NEGOTIABLE)** — authenticated adjudicator identity strengthens the only approval path; no force-approve path is introduced; decision/card/status commit together.
- [x] **II. Licensing-Clean (NON-NEGOTIABLE)** — no dataset is added; COCO evaluation code is installed as a dependency and operates on owned/permissive fixtures; existing fetch-not-commit controls remain.
- [x] **III. Model-Class-Appropriate** — classification coverage rules and COCO-compatible detection metrics remain class-specific; per-class safety recall remains mandatory.
- [x] **IV. Reproducibility & Contamination** — evaluator versions/configuration and checksums are recorded; dependencies are locked; sandbox and append-only evidence are strengthened.
- [x] **V. Verify-First, No Fabrication** — confidence coverage is removed as grounding; unavailable evidence is explicit; lifecycle and Model Card evidence are atomic.
- [x] **VI. Test-First** — all gating/security/durability tasks begin with failing unit, contract, integration, migration, or sandbox tests.

## Architecture

### Request and authorization path

1. FastAPI validates bearer tokens against configured OIDC issuer/audience/algorithms and cached JWKS.
2. Route dependencies enforce roles and expose a typed `Principal` to handlers.
3. Audit actors and adjudication reviewers come from `Principal.subject`; request bodies carry only decision/rationale.
4. `/healthz` stays public and reveals no sensitive configuration; authenticated `/readyz` reports dependency/schema readiness.

### Artifact ingestion path

1. Stream the upload to a UUID-named `.part` file while counting bytes and hashing SHA-256.
2. Abort at the configured maximum regardless of `Content-Length`.
3. Validate framework/extension compatibility and safe filename metadata.
4. In one database transaction create the Model/ModelVersion/ArtifactReceipt and Evaluation JobIntent.
5. Atomically rename the `.part` file to its immutable digest-addressed location immediately before commit; compensate the file on rollback.

### Durable execution path

1. Domain transactions insert a unique `JobIntent` with an idempotency key.
2. A dispatcher uses `FOR UPDATE SKIP LOCKED` on PostgreSQL, publishes to RQ, and records attempts/delivery timestamps with retry/backoff.
3. A worker claims the intent in the database. Existing completed/active claims make redelivery a no-op with audit telemetry.
4. Inline test/demo mode invokes the same claim/evaluate code without Redis.

### Evaluation and completion path

1. Sandbox output passes structural and coverage validation before metrics.
2. Classification accounts for every annotation key; detection uses pinned COCO evaluation.
3. Tier outcomes carry coverage and evaluator provenance.
4. The orchestrator renders the Model Card from in-memory outcome/decision inputs before final persistence.
5. A single transaction inserts the append-only run/tier/audit rows, applies status, and inserts/updates the current Model Card.

### Grounding path

1. Adapters/evaluators may return a typed `GroundingEvidence` only when the method is supported and linked to labeled targets.
2. Tier 3 validates required fields and score bounds.
3. Unsupported/insufficient evidence records `unavailable`; no confidence-derived fallback exists.
4. The initial implementation supports explicit stub evidence for tests and a reference pointing-game/energy-inside-region evaluator for supported CV attribution outputs; other adapters route to review until implemented.

### Sandbox boundary

- API has no container-runtime socket.
- A dedicated runner process/service owns the minimum container-launch privilege; production guidance requires rootless Docker/Podman or a constrained socket proxy.
- Each model container uses non-root UID/GID, `cap_drop: ALL`, `no-new-privileges`, read-only root/input mounts, no network, bounded tmpfs/output, PID/CPU/memory/time limits, and an explicit seccomp profile.
- The runner validates requested mount sources against configured roots and never accepts arbitrary container options from an artifact or API request.

## Project Structure

### Documentation (this feature)

```text
specs/002-production-hardening/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── tasks.md
├── checklists/
│   └── requirements.md
└── contracts/
    ├── openapi.yaml
    ├── metric-evidence.md
    └── security-boundary.md
```

### Source Code (repository root)

```text
backend/
├── alembic.ini
├── migrations/
│   ├── env.py
│   └── versions/
├── app/
│   ├── api/
│   │   ├── auth.py
│   │   ├── models.py
│   │   ├── golden_sets.py
│   │   └── adjudication.py
│   ├── db/
│   │   ├── models.py
│   │   └── repositories.py
│   └── services/
│       ├── artifact_ingest.py
│       ├── auth.py
│       ├── dispatcher.py
│       └── orchestrator.py
├── engine/
│   ├── metrics/
│   │   ├── coverage.py
│   │   ├── classification.py
│   │   └── detection.py
│   ├── sandbox/
│   │   └── runner.py
│   └── tiers/
│       └── tier3_ops.py
├── tests/
│   ├── contract/
│   ├── integration/
│   ├── migration/
│   └── unit/
└── uv.lock

frontend/
├── src/
│   ├── auth/
│   ├── api/client.ts
│   └── pages/
├── tests/
└── package-lock.json

docker/
├── api.Dockerfile
├── sandbox.Dockerfile
└── sandbox-seccomp.json

.github/workflows/ci.yml
docker-compose.yml
```

**Structure Decision**: Extend the existing web-application layout. Keep security, ingestion, dispatch, scoring validation, and orchestration as focused modules rather than expanding route files. Add migrations and dedicated tests without introducing a new application framework.

## Delivery Phases

1. **Security and reproducibility foundation**: dependency lock/scans, configuration model, migrations, OIDC principal/roles, audit actor propagation.
2. **Integrity-critical P1 slices**: classification/detection accounting, bounded upload, atomic completion/adjudication, durable job intents.
3. **Evidence and isolation**: grounding contract/evaluator, sandbox runner boundary and hardening.
4. **Frontend/operations**: OIDC browser flow, removal of reviewer field, production compose/runbook, migration and outage validation.

Each slice retains independent tests and can merge only when all existing Constitution gates pass.

## Complexity Tracking

| Addition | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| Transactional job outbox | Submission/re-evaluation must survive Redis outages and duplicate delivery | Direct `commit` then `enqueue` loses work or returns partial success when Redis is unavailable |
| External OIDC integration | Privileged approvals require verified, revocable identity without storing passwords | Client-supplied reviewer names and static shared API keys do not provide accountable human identity |
| Dedicated sandbox runner boundary | Untrusted model formats execute code while container launch authority is privileged | Mounting the unrestricted runtime socket into the general worker makes worker compromise host-equivalent |
