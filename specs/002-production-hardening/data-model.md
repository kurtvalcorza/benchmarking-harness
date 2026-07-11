# Data Model: Production Hardening and Evaluation Integrity

**Feature**: `002-production-hardening`
**Date**: 2026-07-11

Feature 002 extends the Feature 001 schema. Existing append-only entities remain append-only. Production uses PostgreSQL migrations; field types below are logical and may map differently in SQLite tests.

## Existing entities changed

### ModelVersion

Add:

| Field | Type | Rules |
|---|---|---|
| `submitted_by` | string | Required stable authenticated principal subject |
| `artifact_receipt_id` | UUID FK | Required after a successful Feature 002 upload; unique |

`artifact_ref` remains during migration for compatibility, then becomes derived from the receipt or is removed in a later feature. Status transitions remain governed by Feature 001.

### TierResult (append-only)

Add:

| Field | Type | Rules |
|---|---|---|
| `coverage` | JSON object | Required for scored Tier 1/Tier 2 results; shape below |
| `evaluator` | JSON object | Required for every scored result; name/version/configuration |
| `evidence_digest` | SHA-256 string | Required when `evidence_ref` is non-empty |

Existing `metrics`, `threshold`, `dataset_checksum`, and `evidence_ref` remain. No update/delete is permitted.

### AdjudicationRecord (append-only)

`reviewer` is populated only from `AuthenticatedPrincipal.subject`. The decision request no longer contains a reviewer field. Add optional `reviewer_display` as captured non-authoritative display text for audit readability.

### AuditEvent (append-only)

Add optional fields:

- `request_id`: correlation identifier.
- `principal_issuer`: identity issuer for authenticated events.
- `outcome`: `success`, `denied`, or `failure`.
- `metadata`: sanitized JSON details; MUST NOT contain access tokens or model payload bytes.

## New value objects

### AuthenticatedPrincipal (not persisted as a user table)

| Field | Type | Rules |
|---|---|---|
| `subject` | string | Required stable `iss + sub` identity key |
| `issuer` | URI | Must equal configured issuer |
| `display` | string/null | Optional email/name for UI only |
| `roles` | set of enum | Subset of `submitter`, `governance`, `adjudicator`, `auditor` |
| `token_id` | string/null | Optional hashable audit correlation; raw token never stored |

### PredictionCoverage

Stored in `TierResult.coverage`:

| Field | Type | Rules |
|---|---|---|
| `expected_count` | integer | >=0; denominator from registered dataset |
| `received_count` | integer | >=0; raw predictions received |
| `scored_count` | integer | >=0; expected items accounted for |
| `missing_count` | integer | >=0 |
| `duplicate_count` | integer | >=0 |
| `unexpected_count` | integer | >=0 |
| `valid` | boolean | False for structural/duplicate/unexpected output errors |
| `issues` | array of object | Bounded examples/codes; never unbounded raw predictions |

Invariants:

- Classification: `scored_count == expected_count` for every valid score; missing items contribute incorrect outcomes.
- `duplicate_count > 0` or `unexpected_count > 0` makes classification output invalid.
- Counts and issue samples are generated before metric calculation.

### EvaluatorProvenance

Stored in `TierResult.evaluator`:

| Field | Type | Rules |
|---|---|---|
| `name` | string | e.g. `pycocotools.cocoeval`, `harness.classification` |
| `version` | string | Installed evaluator/harness version |
| `metric_contract` | string | Versioned contract identifier |
| `configuration` | JSON object | IoU thresholds, max detections, averaging, tolerance, deterministic settings |
| `label_map_digest` | SHA-256/null | Digest when a label map is applied |
| `dataset_checksum` | SHA-256 | Must equal TierResult dataset checksum |

### GroundingEvidence

Stored within Tier 3 metrics/evidence:

| Field | Type | Rules |
|---|---|---|
| `status` | enum | `measured` or `unavailable` |
| `method` | string/null | Required when measured; approved method identifier |
| `evaluator_version` | string/null | Required when measured |
| `score` | float/null | Finite [0,1] when measured |
| `sample_count` | integer | >0 and >= configured minimum when measured |
| `target_ref` | string/null | Labeled target set reference/checksum |
| `evidence_ref` | string/null | Required when measured |
| `evidence_digest` | SHA-256/null | Required when measured |
| `unavailable_reason` | enum/null | Required when unavailable |

`unavailable_reason`: `unsupported_framework`, `unsupported_model_class`, `missing_attribution`, `insufficient_samples`, `invalid_evidence`.

## New persisted entities

### ArtifactReceipt (immutable)

| Field | Type | Rules |
|---|---|---|
| `id` | UUID | Primary key |
| `storage_ref` | string | Immutable finalized artifact path/object key; unique |
| `original_filename` | string | Sanitized metadata only |
| `byte_count` | bigint | >0 and <= configured maximum at ingestion |
| `sha256` | char(64) | Required lowercase hex; indexed |
| `framework` | string | Must agree with ModelVersion declaration |
| `submitted_by` | string | Authenticated subject |
| `finalized_at` | timestamp UTC | Required |

No update/delete through application repositories. Cleanup of an unreferenced failed receipt is a compensating operation before commit, not lifecycle mutation.

### JobIntent

| Field | Type | Rules |
|---|---|---|
| `id` | UUID | Primary key |
| `kind` | enum | `evaluate_model_version` |
| `model_version_id` | UUID FK | Required |
| `golden_set_id` | UUID/null | Target set captured for re-evaluation intent; null means resolve current at claim time only for initial submission |
| `reason` | enum | `submission`, `golden_set_update`, `mid_run_staleness`, `operator_retry` |
| `idempotency_key` | string | Unique; deterministic from logical request |
| `state` | enum | See transition table |
| `attempt_count` | integer | >=0 |
| `available_at` | timestamp UTC | Retry/backoff eligibility |
| `last_error` | string/null | Sanitized bounded message |
| `created_at` | timestamp UTC | Required |
| `dispatched_at` | timestamp UTC/null | Set after transport publish |
| `claimed_at` | timestamp UTC/null | Set by worker claim |
| `completed_at` | timestamp UTC/null | Set with domain completion |

Unique constraint: `idempotency_key`.

Transitions:

```text
pending -> dispatching -> dispatched -> claimed -> completed
   ^           |              |           |
   |           +-> failed ----+           +-> failed
   +---------------- retryable failed/expired lease
```

Rules:

- Dispatch leasing uses row locks in PostgreSQL and a lease timestamp/owner in implementation fields if needed.
- `completed` is terminal.
- A duplicate create with the same idempotency key returns the existing intent.
- A duplicate transport delivery of `completed` performs no new evaluation.

### JobAttempt (append-only)

| Field | Type | Rules |
|---|---|---|
| `id` | UUID | Primary key |
| `job_intent_id` | UUID FK | Required |
| `attempt_number` | integer | Unique with intent; starts at 1 |
| `worker_id` | string | Required for claimed attempts |
| `transport_job_id` | string/null | RQ identifier |
| `started_at` | timestamp UTC | Required |
| `finished_at` | timestamp UTC/null | Required when terminal |
| `outcome` | enum | `claimed`, `duplicate`, `completed`, `retryable_failure`, `terminal_failure` |
| `run_id` | UUID/null | Logical EvaluationRun produced by successful completion |
| `error_code` | string/null | Stable typed code |

Unique constraint on `(job_intent_id, attempt_number)`. No updates/deletes except completing the attempt inside its transaction; after terminalization it is treated append-only. If strict append-only semantics are required, model start/finish as separate events instead.

### Schema metadata

Alembic's `alembic_version` table is the schema revision source of truth. The application expects a configured/head revision in production. It is operational metadata, not domain history.

## Transaction boundaries

### Successful submission

1. Stream/hash temporary file outside the database transaction.
2. Begin transaction.
3. Create/find Model; insert ModelVersion, ArtifactReceipt, AuditEvent, and JobIntent.
4. Atomically finalize artifact file.
5. Commit. On any failure, roll back and remove finalized/temp file if it was created by this attempt.

### Successful evaluation completion

In one transaction:

- insert EvaluationRun (complete), TierResults, completion AuditEvents;
- update mutable ModelVersion status;
- insert/update current ModelCard using pre-rendered content;
- mark JobIntent completed and finalize JobAttempt.

### Successful adjudication

In one transaction:

- insert AdjudicationRecord and AuditEvent;
- update ModelVersion status;
- insert/update current ModelCard using pre-rendered content.

Failure before commit leaves none of these visible.

## Migration sequence

1. `0001_feature_001_baseline`: declarative baseline matching the schema created by Feature 001.
2. `0002_hardening_entities`: add ArtifactReceipt, JobIntent/JobAttempt, new columns/indexes/constraints.
3. Data migration for existing ModelVersions: compute receipts from accessible artifacts, mark missing artifacts explicitly, and set legacy `submitted_by` to a configured migration principal such as `legacy:feature-001`.
4. Enforce new non-null constraints only after backfill validation.

Production upgrade documentation MUST require a backup and dry-run on a copy before step 3.
