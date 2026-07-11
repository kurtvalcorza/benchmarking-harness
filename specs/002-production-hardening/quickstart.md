# Quickstart and Validation: Production Hardening

**Feature**: `002-production-hardening`
**Audience**: implementers and reviewers
**Status**: planned workflow; commands become executable as tasks land

## Prerequisites

- Python 3.11 and the repository's locked Python environment toolchain
- Node.js 22 and `npm ci`
- Docker-compatible runtime with Compose
- PostgreSQL and Redis (provided by the Feature 002 Compose profile)
- A local OIDC test issuer or the explicit dev-token helper

No third-party dataset or production model is needed. Use the committed owned sample data and stub artifacts.

## 1. Install reproducibly

```bash
uv sync --frozen --all-extras
cd frontend
npm ci
cd ..
```

Expected:

- dependency resolution does not modify `uv.lock` or `package-lock.json`;
- `uv run pip-audit` and `npm audit` have no unexcepted high/critical advisory;
- the current Vite/Vitest advisories from Feature 001 are absent.

## 2. Start production-like dependencies and migrate

```bash
docker compose --profile production up -d postgres redis runner
uv run alembic -c backend/alembic.ini upgrade head
uv run python -m app.services.schema_check
```

Expected:

- PostgreSQL reaches the Feature 002 head revision;
- schema check reports `current`;
- rerunning `alembic upgrade head` is a no-op;
- the API does not call `create_all` in production mode.

## 3. Create local test identities

```bash
uv run python scripts/dev_token.py --subject alice --role submitter
uv run python scripts/dev_token.py --subject grace --role governance
uv run python scripts/dev_token.py --subject adi --role adjudicator
uv run python scripts/dev_token.py --subject audit --role auditor
```

The helper is available only with `HARNESS_AUTH_MODE=dev` and refuses `HARNESS_ENV=production`. Store emitted tokens in shell variables; never commit them.

## 4. Run the API and dispatcher

```bash
$env:HARNESS_ENV = "development"
$env:HARNESS_AUTH_MODE = "dev"
$env:HARNESS_DATABASE_URL = "postgresql+psycopg://harness:harness@localhost:5432/harness"
$env:HARNESS_REDIS_URL = "redis://localhost:6379/0"
uv run uvicorn app.main:app --app-dir backend --port 8000
```

In separate terminals:

```bash
uv run python -m app.services.dispatcher
uv run python -m worker.main
```

Expected authorization probes:

- `GET /healthz` without a token -> `200`.
- any other endpoint without a token -> `401`.
- Golden Set registration with a submitter token -> `403`.
- the same registration with a governance token -> success.

## 5. Validate bounded upload behavior

Set a small limit for the test:

```bash
$env:HARNESS_MAX_UPLOAD_BYTES = "1024"
```

Submit a 1,024-byte fixture and a 1,025-byte fixture through the authenticated endpoint.

Expected:

- 1,024 bytes succeeds and returns an Artifact Receipt with exact byte count and SHA-256;
- 1,025 bytes returns `413`;
- no `.part` file, Model Version, Artifact Receipt, or Job Intent remains for the rejected upload;
- the successful response contains a durable `evaluation_intent` even if Redis is stopped.

## 6. Validate queue outage recovery

1. Stop Redis.
2. Submit an in-limit stub model with a submitter token.
3. Confirm the request returns `201` and the intent is `pending`.
4. Start Redis and the dispatcher.
5. Confirm the same intent reaches `completed` and exactly one logical Evaluation Run references it.
6. Redeliver the transport job and confirm no second logical run appears.

## 7. Validate metric coverage

```bash
uv run pytest backend/tests/unit/test_classification_coverage.py -q
uv run pytest backend/tests/unit/test_detection_coco.py -q
```

Required fixtures:

- classification: all predictions, one missing, one duplicate, one unexpected, NaN score;
- detection: empty detections, missing envelope, mismatched arrays, invalid boxes/scores, deterministic COCO reference fixture.

Expected:

- missing classification prediction lowers metrics and denominator remains expected dataset size;
- duplicate/unexpected output is typed invalid output;
- COCO metrics agree with direct pinned reference output within `1e-6`;
- evidence records coverage and evaluator provenance.

## 8. Validate atomic completion and adjudication

```bash
uv run pytest backend/tests/integration/test_atomic_completion.py -q
uv run pytest backend/tests/integration/test_atomic_adjudication.py -q
```

Inject card-render, evidence-publish, and commit failures. After each failure verify:

- no final status without the corresponding current card;
- no permanent adjudication record after an error response;
- no orphaned finalized evidence is presented as committed;
- retry succeeds once the injected fault is removed.

## 9. Validate grounding semantics

```bash
uv run pytest backend/tests/unit/test_grounding_evidence.py -q
uv run pytest backend/tests/integration/test_tier3_grounding.py -q
```

Expected:

- measured evidence contains method/version/sample/target/ref/digest;
- confidence-only predictions produce `unavailable`, never a grounding score;
- insufficient samples cannot pass the grounding threshold.

## 10. Validate sandbox controls

```bash
uv run pytest backend/tests/contract/test_sandbox_hardening.py -q
uv run pytest backend/tests/integration/test_sandbox_runtime.py -q
```

On a supported runtime, the probe must demonstrate:

- non-root UID/GID;
- empty effective capabilities and no-new-privileges;
- failed network egress;
- failed writes to root, code, artifact, and dataset mounts;
- bounded writable temp/output;
- PID, memory, and timeout enforcement;
- API/worker processes do not hold an unrestricted runtime socket.

## 11. Run all gates

```bash
uv run ruff check backend scripts
uv run pytest backend/tests -q
cd frontend
npm run lint
npm run build
npm test
npm audit
cd ..
docker compose config --quiet
uv run pip-audit
```

Also run the Constitution gates unchanged:

```bash
uv run pytest backend/tests/contract/test_no_restricted_data.py -q
uv run pytest backend/tests/contract/test_no_auto_approval.py -q
uv run pytest backend/tests/contract/test_sandbox_no_egress.py -q
```

## Acceptance record

Implementation is ready for Feature 002 acceptance only when:

- every task selected for the release is checked in `tasks.md`;
- every requirement checklist item remains satisfied;
- FR-to-test traceability is produced and has no gaps;
- migration is tested from empty and Feature 001 baseline;
- security and outage fault-injection scenarios are recorded in `validation.md` during implementation;
- no non-negotiable Constitution principle has a waiver.
