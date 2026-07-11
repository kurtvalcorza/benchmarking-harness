# Feature Specification: Production Hardening and Evaluation Integrity

**Feature Branch**: `002-production-hardening`

**Created**: 2026-07-11

**Status**: Draft

**Input**: User description: "Harden the model benchmarking harness after a full code review: protect privileged operations, bound uploads, make benchmark accounting complete and standards-based, keep evaluation status and Model Cards consistent, replace confidence-as-grounding, strengthen sandbox isolation, and add production-grade persistence and dependency controls."

**Constitution**: governed by v1.0.0 (`.specify/memory/constitution.md`). Principles I (Human-in-the-Loop) and II (Licensing-Clean) remain non-negotiable.

## Clarifications

### Session 2026-07-11

- Q: Is this a new product surface or a brownfield hardening feature? -> A: **Brownfield hardening** of the existing API, worker, evaluation engine, frontend, and deployment. Existing POC behavior remains available where it does not conflict with the security and evidence requirements below.
- Q: Where do user identities come from? -> A: An **external OpenID Connect identity provider** issues signed access tokens. The harness validates tokens and role claims; it does not store passwords or issue production credentials.
- Q: Which roles are needed? -> A: `submitter`, `governance`, `adjudicator`, and `auditor`. A principal may hold multiple roles. Reviewer identity is derived from the authenticated principal and is never accepted from request data.
- Q: What upload boundary applies? -> A: A configurable server-side maximum, **2 GiB by default**, enforced while streaming and paired with the ingress/proxy limit. Partial uploads are removed and never become Model Versions.
- Q: What counts as visual grounding? -> A: Only a documented localization/attribution measurement tied to labeled evidence. **Confidence coverage is not grounding** and cannot satisfy the Tier 3 grounding gate.
- Q: What is the production database/queue target? -> A: PostgreSQL with schema migrations and a transactional job outbox. SQLite and inline execution remain supported for tests and the offline demo.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Trusted identities perform only authorized actions (Priority: P1)

An authenticated user accesses the harness and can perform only the operations assigned to their role. Adjudication records use the verified identity from the access token.

**Why this priority**: The current governance and approval operations decide which models may enter a repository. Unauthenticated or self-asserted identities make the human gate unauditable.

**Independent Test**: Exercise each protected endpoint with no token, a token lacking the required role, and a correctly authorized token; verify `401`, `403`, and success respectively, and verify the stored actor matches the token subject.

**Acceptance Scenarios**:

1. **Given** no valid access token, **When** a client calls any non-health endpoint, **Then** the request is rejected with `401` and no state changes.
2. **Given** a valid `submitter` token, **When** the user uploads a model, **Then** the submission is accepted and its audit event records the authenticated subject.
3. **Given** a valid token without the `governance` role, **When** the user attempts to register a Golden Test Set, **Then** the request is rejected with `403`.
4. **Given** an `adjudicator` records a decision, **When** the permanent record is created, **Then** reviewer identity comes from the verified token and cannot be overridden by request data.
5. **Given** production mode, **When** authentication configuration is absent or invalid, **Then** the service fails closed at startup.

---

### User Story 2 - Every evaluated item is accounted for correctly (Priority: P1)

A governance owner trusts that capability and stress scores cover the complete registered dataset and use the standard metric for the model class.

**Why this priority**: A gate can approve an unsafe model if missing predictions are silently excluded or if a simplified metric is presented as a standard benchmark.

**Independent Test**: Score deliberately incomplete, duplicate, extra, and valid prediction sets for classification and detection; verify invalid coverage cannot inflate a score and valid fixtures match a reference evaluator.

**Acceptance Scenarios**:

1. **Given** a classification dataset with an annotation for every image, **When** a model omits an image prediction, **Then** that image counts as incorrect and the coverage discrepancy is recorded.
2. **Given** duplicate or unknown image identifiers in predictions, **When** scoring begins, **Then** the run records a typed evaluation error rather than choosing a favorable prediction silently.
3. **Given** a detection run, **When** the metric is calculated, **Then** AP/mAP is produced by a standards-compatible COCO evaluator and agrees with the pinned reference implementation within tolerance.
4. **Given** a score result, **When** it is persisted, **Then** it includes expected item count, received item count, missing count, duplicate count, unexpected count, evaluator name, evaluator version, and metric configuration.

---

### User Story 3 - Large model uploads fail safely (Priority: P1)

A submitter uploads valid model weights without exposing the service to unlimited disk consumption or leaving partial artifacts behind.

**Why this priority**: Model files are intentionally large, but an unbounded upload can exhaust shared storage and stop all evaluations.

**Independent Test**: Upload files just below, exactly at, and one byte above the configured limit, plus an interrupted stream; verify the first two succeed, oversized input returns `413`, and no partial Model Version or artifact remains after failure.

**Acceptance Scenarios**:

1. **Given** an upload within the configured maximum, **When** streaming completes, **Then** the artifact is atomically finalized and its byte count and SHA-256 digest are stored.
2. **Given** an upload larger than the configured maximum, **When** the limit is crossed, **Then** streaming stops, the response is `413`, and temporary data and database rows are removed.
3. **Given** an interrupted or failed upload, **When** cleanup runs, **Then** no partially uploaded artifact can be evaluated.
4. **Given** service startup, **When** the application and ingress limits disagree, **Then** the effective limit is visible in configuration diagnostics and documented for operators.

---

### User Story 4 - Completion is durable and internally consistent (Priority: P1)

A submitter or adjudicator receives a definitive response: either the requested lifecycle change and its Model Card are committed together, or neither is committed. Evaluation work is not lost when the queue is briefly unavailable.

**Why this priority**: A completed run, approval decision, and Model Card form one evidence package. Partial success creates misleading API errors and stale audit artifacts.

**Independent Test**: Inject failures during card generation, database commit, queue publication, and duplicate job delivery; verify no split-brain lifecycle state and eventual execution exactly once at the domain level.

**Acceptance Scenarios**:

1. **Given** Model Card generation fails before an evaluation completion commit, **When** the transaction ends, **Then** no final model status or completed run is committed.
2. **Given** Model Card regeneration fails during adjudication, **When** the request returns an error, **Then** no adjudication decision or status change has been committed.
3. **Given** a model submission commits while Redis is unavailable, **When** the dispatcher recovers, **Then** the durable evaluation intent is published without resubmission.
4. **Given** the same job is delivered more than once, **When** workers claim it, **Then** one logical evaluation/adjudication side effect occurs and duplicates are recorded without corrupting state.

---

### User Story 5 - Tier 3 reports defensible evidence (Priority: P1)

An adjudicator can distinguish a measured visual-grounding result from unavailable evidence and can trace the method to labeled samples.

**Why this priority**: Confidence is not interpretability. Treating it as grounding can falsely satisfy an approval gate.

**Independent Test**: Run a model with valid localization evidence and one without a supported grounding method; verify the first stores method/version/sample evidence and the second reports `unavailable` and cannot silently pass the grounding gate.

**Acceptance Scenarios**:

1. **Given** a supported grounding evaluator, **When** Tier 3 runs, **Then** it records a method identifier, evaluator version, sample count, labeled target reference, score, threshold, and evidence artifact.
2. **Given** no supported grounding evaluator, **When** Tier 3 runs, **Then** grounding is `unavailable`, the value is not fabricated from confidence, and the run follows the unratified/unavailable evidence rule.
3. **Given** an adapter-reported grounding value without verifiable evidence, **When** Tier 3 validates it, **Then** the value is rejected as insufficient evidence.

---

### User Story 6 - Operators can deploy and maintain the harness safely (Priority: P2)

An operator deploys the service with reproducible dependencies, migrated storage, hardened sandbox execution, and security checks in CI.

**Why this priority**: These controls reduce operational and supply-chain risk but build on the correctness and authorization gates above.

**Independent Test**: Start a fresh production-like stack, migrate an existing POC database copy, run a malicious-model sandbox probe, and execute dependency/security CI gates.

**Acceptance Scenarios**:

1. **Given** a clean PostgreSQL database, **When** migrations run, **Then** the complete schema is created without application `create_all` behavior.
2. **Given** an existing supported schema revision, **When** upgrading, **Then** data is preserved and the application refuses to start against an unknown or behind revision unless explicitly in development mode.
3. **Given** untrusted model code, **When** its sandbox starts, **Then** it runs as non-root with all capabilities dropped, no-new-privileges, a read-only root, no egress, resource limits, and only explicit read-only inputs plus a bounded output mount.
4. **Given** a dependency with a known disallowed-severity advisory, **When** CI runs, **Then** the build fails with the affected package and remediation path.

### Edge Cases

- A token is correctly signed but has the wrong issuer, audience, expiry, or clock window.
- An authenticated principal has multiple roles or no recognized harness role.
- The identity provider is unavailable after signing keys have been cached, or rotates keys while the service is running.
- `Content-Length` is missing, false, or smaller than the actual streamed body.
- An upload filename contains traversal syntax, reserved Windows names, Unicode normalization collisions, or an unsupported extension.
- Disk becomes full after streaming begins but before atomic finalization.
- Predictions include NaN/infinite scores, mismatched detection array lengths, duplicate image IDs, or image IDs outside the dataset.
- The expected dataset contains an intentionally empty annotation entry.
- Card generation succeeds but the database transaction fails; temporary evidence must not appear committed.
- An outbox message is published but acknowledgement persistence fails, causing redelivery.
- A migration is interrupted and rerun.
- The container runtime is unavailable or sandbox hardening options are unsupported.
- A grounding method produces no valid samples after filtering.
- A vulnerability scanner is temporarily unavailable; release behavior must fail closed while local development may use a documented override.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Every API endpoint except `/healthz` and explicitly documented readiness metadata MUST require a valid access token.
- **FR-002**: The API MUST validate access-token signature, issuer, audience, expiry/not-before, and allowed algorithms against configured OpenID Connect metadata; production startup MUST fail closed when validation cannot be configured.
- **FR-003**: The system MUST authorize operations by role: `submitter` for model submission/read-own submission, `governance` for Golden Test Set registration, `adjudicator` for queue/decision operations, and `auditor` for cross-model evidence/history reads. Read rules MUST be explicit in the API contract.
- **FR-004**: Actor/reviewer identity MUST be derived from the authenticated principal and MUST NOT be accepted as authoritative request data.
- **FR-005**: Authorization successes and failures for privileged lifecycle operations MUST create security/audit telemetry without logging raw access tokens.
- **FR-006**: Model uploads MUST be streamed through a temporary file with a configurable maximum size (default 2 GiB), byte count, and SHA-256 digest; successful completion MUST use atomic finalization.
- **FR-007**: Oversized, interrupted, unsupported, or failed uploads MUST leave no evaluable Model Version and no partial artifact; oversized input MUST return HTTP `413`.
- **FR-008**: The configured application upload limit and required ingress/proxy limit MUST be documented and exposed in non-secret operator diagnostics.
- **FR-009**: Classification scoring MUST account for every expected dataset image exactly once; missing predictions count as incorrect, while duplicate or unexpected image IDs produce a typed invalid-output result.
- **FR-010**: Scoring MUST validate finite numeric values and class-appropriate prediction shapes before metric calculation.
- **FR-011**: Detection AP/mAP MUST use a pinned, standards-compatible COCO evaluation implementation; simplified approximations MUST use a different metric name and MUST NOT satisfy a COCO mAP threshold.
- **FR-012**: Every score result MUST record coverage counts and evaluator provenance: expected, received, missing, duplicate, unexpected, evaluator name/version, configuration, and dataset checksum.
- **FR-013**: Evaluation completion MUST commit the completed run, tier results, final Model Version status, audit event, and current Model Card atomically, or commit none of them.
- **FR-014**: Adjudication MUST commit the permanent decision, status transition, audit event, and regenerated Model Card atomically, or commit none of them.
- **FR-015**: Model Card generation MUST be deterministic from transaction-local inputs and MUST not require reading records that have already been committed as a prerequisite to rendering.
- **FR-016**: Model submissions and Golden Test Set re-evaluation triggers MUST create durable job intents in the same transaction as their domain change.
- **FR-017**: A dispatcher MUST publish pending job intents with retry/backoff and record delivery state; workers MUST implement idempotent domain claims so at-least-once delivery cannot create duplicate logical runs.
- **FR-018**: Queue unavailability MUST NOT require a user to repeat a successfully committed submission or Golden Test Set registration.
- **FR-019**: Tier 3 MUST NOT derive or label visual grounding from prediction confidence coverage.
- **FR-020**: A passing grounding result MUST contain verifiable localization/attribution evidence tied to labeled samples, including method, evaluator version, sample count, target reference, score, and evidence artifact.
- **FR-021**: When no supported grounding method or sufficient evidence exists, Tier 3 MUST record grounding as `unavailable`; it MUST route according to the unratified/unavailable evidence rule and MUST NOT silently pass.
- **FR-022**: Production persistence MUST use versioned migrations and PostgreSQL; SQLite MAY remain for tests and the offline demo.
- **FR-023**: Production startup MUST verify the database schema revision; application table creation via `create_all` MUST be limited to explicitly configured test/demo use.
- **FR-024**: The model sandbox MUST run as a non-root UID/GID with all Linux capabilities dropped, no-new-privileges enabled, a read-only root filesystem, no network, PID/CPU/memory/time limits, and only required mounts.
- **FR-025**: The production worker MUST NOT receive unrestricted container-runtime authority except through a documented isolated runner boundary; compromise of the API process MUST not grant container control.
- **FR-026**: Sandbox images and CI actions MUST be version-pinned; runtime and dependency manifests MUST support reproducible builds.
- **FR-027**: CI MUST scan Python and Node dependency graphs and fail on known high/critical vulnerabilities, with time-bound, documented exceptions only.
- **FR-028**: The frontend MUST use supported Vite/Vitest versions and MUST complete authenticated submitter/adjudicator flows without accepting reviewer identity as free text.
- **FR-029**: Tests for authorization, scoring coverage, lifecycle atomicity, durable dispatch, grounding evidence, migrations, and sandbox controls MUST be written to fail before implementation.
- **FR-030**: Existing Constitution gates for human adjudication, licensing cleanliness, no egress, append-only history, and non-fabricated evidence MUST remain green.

### Key Entities

- **Authenticated Principal**: externally issued identity represented by stable subject, issuer, display identifier, and role claims; no local password.
- **Artifact Receipt**: immutable upload metadata containing artifact reference, byte count, SHA-256 digest, original safe filename, media/framework declaration, and finalized timestamp.
- **Prediction Coverage**: validation summary for one score operation: expected/received/missing/duplicate/unexpected counts and invalid-output details.
- **Evaluator Provenance**: evaluator name/version, metric configuration, dataset checksum, and deterministic settings attached to a Tier Result.
- **Grounding Evidence**: measured localization/attribution result with method, version, sample count, labeled target reference, score, threshold, and evidence artifact.
- **Job Intent**: durable request to evaluate or re-evaluate a Model Version, including idempotency key, reason, state, attempts, and timestamps.
- **Job Claim**: worker claim for a Job Intent that prevents duplicate logical evaluation effects under at-least-once delivery.
- **Schema Revision**: migration identifier representing the database contract expected by the running application.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of unauthorized requests to protected endpoints are rejected; 0 adjudication records use a client-supplied reviewer identity.
- **SC-002**: Boundary tests demonstrate that uploads at or below the configured limit succeed and uploads one byte above return `413`, with 0 partial database records or artifacts after every failure case.
- **SC-003**: For classification fixtures with omitted predictions, reported accuracy uses 100% of expected images; incomplete output cannot improve top-1, top-5, macro-F1, or per-class recall.
- **SC-004**: Detection reference fixtures match the pinned COCO evaluator within `1e-6` for deterministic inputs.
- **SC-005**: In fault-injection tests at every completion/adjudication commit boundary, 0 cases produce a final status without the matching current Model Card and permanent evidence.
- **SC-006**: A committed submission is eventually evaluated after a simulated 10-minute queue outage without client resubmission; duplicate delivery creates exactly one logical run for its idempotency key.
- **SC-007**: 100% of passing Tier 3 grounding results include method/version/sample/target/evidence fields; 0 use confidence coverage.
- **SC-008**: Production sandbox probes confirm non-root execution, zero effective capabilities, no-new-privileges, no network egress, read-only inputs/root, and enforcement of PID/memory/time limits.
- **SC-009**: A fresh database and one supported prior schema both migrate successfully in automated tests; production startup rejects a deliberately stale schema.
- **SC-010**: CI reports 0 unexcepted high/critical Python or Node dependency advisories and uses reproducible locked dependency inputs.
- **SC-011**: All existing backend, frontend, and Constitution tests remain green, with new traceability from every FR-001 through FR-030 to at least one task and validation check.

## Assumptions

- A standards-compliant external OpenID Connect provider is available in production; provider selection and account lifecycle are outside this repository.
- Access tokens carry stable subject and role/group claims that can be mapped through configuration.
- The browser frontend uses Authorization Code + PKCE through an OIDC client; command-line clients use bearer tokens obtained outside the harness.
- The default 2 GiB upload limit is an operational default and may be lowered; increasing it requires aligned ingress and storage capacity settings.
- PostgreSQL and Redis remain deployment dependencies in production; SQLite and inline mode are retained only for tests/offline demonstration.
- At-least-once queue delivery is acceptable because idempotency is enforced in the domain/database layer.
- COCO-compatible evaluation is the detection standard for the currently supported detection class.
- Supported grounding methods may initially cover fewer framework/model-class combinations than capability evaluation; unavailable evidence routes to review rather than being fabricated.

## Out of Scope

- Building or operating an identity provider, user directory, password reset, or account-provisioning system.
- Multi-member adjudication or quorum voting.
- Malware classification or proving that arbitrary model formats are safe outside the sandbox.
- Kubernetes-specific deployment manifests, autoscaling, or multi-region disaster recovery.
- Replacing the existing Golden Test Set governance model or adding restricted datasets.
- Implementing drift/shortcut robustness probes deferred by Feature 001.
- Rewriting the frontend design beyond the authentication and reviewer-identity changes required here.
