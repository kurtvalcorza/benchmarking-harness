# Research: Production Hardening and Evaluation Integrity

**Feature**: `002-production-hardening`
**Date**: 2026-07-11

This document records implementation decisions made during Phase 0. It relies on the existing Feature 001 architecture, the project constitution, the code-review evidence that motivated Feature 002, and the repository's installed Spec Kit workflow.

## R1. Authentication and identity

**Decision**: Validate externally issued OpenID Connect JWT access tokens in FastAPI and map configured claims to harness roles. Use Authorization Code + PKCE in the browser. Do not build a local credential store.

**Rationale**:

- Adjudication requires a verified human identity, not a request field.
- OIDC supports institutional identity, revocation/account lifecycle outside the harness, and signed issuer/audience-bound tokens.
- Stateless API validation scales across API replicas; cached JWKS avoids a network request per API call.

**Validation rules**:

- Allow only configured asymmetric algorithms; never accept `none` or an algorithm selected solely by the token.
- Verify issuer, audience, signature, `exp`, `nbf`, and a small configurable clock skew.
- Resolve roles from configured role/group claim paths and reject unknown roles.
- Refresh JWKS on unknown `kid`, cache using provider metadata/cache headers, and fail closed if no valid key is available.
- Never log raw tokens or return signature-validation internals to callers.

**Alternatives rejected**:

- Client-provided reviewer identity: unauthenticated and non-auditable.
- Static API keys: identify applications poorly, lack role-rich human identity, and create manual rotation burden.
- Local username/password: expands scope into password storage, recovery, MFA, and account lifecycle.

## R2. Authorization model

**Decision**: Enforce four roles with least privilege: `submitter`, `governance`, `adjudicator`, `auditor`. Route dependencies declare required roles; service methods receive the typed principal for defense in depth.

**Rationale**: Registration and adjudication are materially different powers. Explicit dependencies make the access matrix reviewable in OpenAPI and testable endpoint by endpoint.

**Read policy**:

- Submitters may read model versions they submitted, including their own results/cards.
- Adjudicators may read the queue, flagged run evidence, and related model details.
- Governance may register Golden Test Sets and read affected re-evaluation status.
- Auditors may read all models, runs, cards, and audit/evaluator metadata.
- Multi-role principals receive the union of permissions.

## R3. Bounded atomic uploads

**Decision**: Stream uploads in fixed chunks to a temporary file while hashing/counting. Enforce the limit from actual bytes, then atomically rename to a digest-addressed immutable path. Align the reverse-proxy limit with the application setting.

**Rationale**: `Content-Length` is optional and untrusted. Chunked counting keeps memory bounded; atomic rename prevents workers from seeing partial artifacts; SHA-256 supports evidence and deduplication diagnostics.

**Failure handling**:

- `413` for size limit, `415` for unsupported artifact media/extension, `422` for semantic mismatch, `507` for exhausted storage where detectable.
- Remove `.part` files on every exception/cancellation.
- Create the durable domain rows only as part of the successful finalization transaction.
- A startup/periodic janitor removes abandoned `.part` files older than a configured age, never finalized artifacts.

## R4. Classification coverage correctness

**Decision**: Treat annotation image IDs as the denominator. Require one classification prediction per expected image; missing predictions are incorrect. Duplicate and unexpected IDs are invalid adapter output and cause a typed infrastructure/evaluator error rather than arbitrary selection.

**Rationale**: Iterating only returned predictions lets omitted hard examples disappear from accuracy/recall denominators. Duplicate selection rules are gameable unless the adapter contract is strict.

**Details**:

- Empty object lists remain valid dataset entries but classification datasets must declare exactly one target label per scored image.
- Missing prediction: increment total and false negative for the truth label; no false-positive label is added.
- Duplicate/unexpected prediction: reject the scoring input and preserve counts/evidence.
- Record expected, received, missing, duplicate, and unexpected counts for every run.

## R5. Detection metric validity

**Decision**: Use a pinned COCO-compatible evaluator (`pycocotools`) for AP@[.50:.95], AP50, and recall where the threshold/card calls the metric COCO mAP. Keep lightweight matching helpers only for diagnostics/tests under distinct names.

**Rationale**: A single precision-times-recall point is not average precision over a confidence-ranked precision-recall curve and must not be presented as COCO mAP.

**Implementation notes**:

- Convert the internal annotations/predictions deterministically to COCO structures with stable integer category/image IDs.
- Validate box coordinates, array lengths, finite scores, score bounds, and category mapping before evaluation.
- Pin evaluator version and record IoU range, max detections, area ranges, and label-map digest in evaluator provenance.
- Compare deterministic fixtures against direct reference-evaluator output within `1e-6`.

## R6. Atomic lifecycle and Model Cards

**Decision**: Render Model Card content from transaction-local domain inputs before the final database commit, then persist the run/tier rows, status, audit event, and card in one transaction. Apply the same rule to adjudication.

**Rationale**: Committing lifecycle status before card generation produces a completed/approved model with stale or missing evidence when rendering fails, while the caller sees an error after a permanent side effect.

**Evidence files**:

- Write evidence to a temporary run directory first.
- Compute digests and render the card using the temporary/final intended references.
- Atomically publish the evidence directory immediately before commit; remove it on rollback.
- A reconciliation check reports orphaned evidence paths but never invents database state from files.

## R7. Durable job dispatch and idempotency

**Decision**: Add a PostgreSQL transactional outbox (`JobIntent`) and database-backed idempotent claim. RQ remains transport, not the source of truth.

**Rationale**: Database commit followed by direct enqueue has a dual-write gap. At-least-once delivery is expected; domain idempotency is more reliable than assuming exactly-once transport.

**State model**: `pending -> dispatching -> dispatched -> claimed -> completed|failed`, with retry from expired `dispatching`/retryable `failed`. Attempts and timestamps are retained. A unique idempotency key represents one logical requested evaluation reason/set/version.

**Alternative rejected**: enqueue before commit can execute an invisible version; enqueue after commit can lose a committed submission. Distributed transactions with Redis are disproportionate and poorly supported.

## R8. Grounding evidence

**Decision**: Remove confidence-coverage fallback. A `GroundingEvidence` result is valid only when it identifies a supported method and points to reproducible labeled-sample evidence. Initially support test/stub evidence plus reference attribution localization where the adapter emits compatible attribution maps.

**Rationale**: Confidence measures certainty, not spatial explanation quality. A wrong but confident model can score highly.

**Initial metrics**:

- Classification attribution: pointing-game accuracy and/or fraction of positive attribution energy inside annotated target regions.
- Detection attribution: localization overlap/energy relative to the matched ground-truth region where method support exists.
- Minimum sample count is configured and recorded. No valid samples means `unavailable`, not zero and not pass.

**Alternative rejected**: continue proxy but rename it. Even renamed, using confidence to satisfy an interpretability gate remains misleading.

## R9. Database migrations and production storage

**Decision**: Introduce Alembic and PostgreSQL as production storage. Generate a baseline revision matching Feature 001, followed by Feature 002 changes. Keep SQLite fixtures for unit/contract tests and the offline demo.

**Rationale**: `create_all` cannot evolve existing schemas and SQLite offers insufficient concurrency/locking semantics for multi-worker outbox claims.

**Migration policy**:

- Application production startup checks, but does not auto-run, migrations.
- Deployment runs `alembic upgrade head` as an explicit step.
- CI tests upgrade from empty and from the Feature 001 baseline; downgrade support is documented per revision but destructive downgrades are not required.
- SQLite test setup may create/migrate ephemeral schemas explicitly.

## R10. Sandbox hardening

**Decision**: Separate container-launch authority from the API/general worker, prefer rootless runtime or constrained socket proxy, and apply non-root/capability/seccomp/mount/resource controls to every model container.

**Rationale**: No-egress protects datasets from ordinary network exfiltration, but untrusted PyTorch deserialization can execute code. Running it as root with default capabilities and exposing the unrestricted runtime socket to a broad worker increases host-compromise impact.

**Required runtime assertions**:

- UID/GID are non-zero.
- effective capability set is empty and no-new-privileges is set.
- network namespace has no usable egress.
- root filesystem and input mounts reject writes.
- only the per-run output mount/tmpfs is writable and bounded.
- PID/memory/timeout limits terminate probes as designed.

## R11. Dependency and supply-chain controls

**Decision**: Lock Python and Node dependency graphs, update Vite/Vitest to supported non-vulnerable releases, scan both graphs in CI, pin container base images by digest, and pin GitHub Actions by immutable commit SHA with version comments.

**Rationale**: The review found five development-chain Node advisories, including high/critical reports. Unbounded Python ranges and floating container/action tags reduce reproducibility.

**Exception policy**: Any temporary advisory exception records advisory ID, affected component, exposure analysis, owner, approval, and expiry no later than 30 days. High/critical findings without a current exception block merge/release.

## R12. Spec Kit lifecycle completeness

**Decision**: Deliver specification, clarification decisions, implementation plan, Phase 0 research, Phase 1 data model/contracts/quickstart, quality checklist, and story-organized task list. Run cross-artifact traceability checks before implementation.

**Rationale**: Current upstream Spec Kit describes the flow as constitution -> specify -> clarify -> plan -> tasks -> analyze -> implement. This package stops before implementation but includes every artifact needed to run the analyze/implement phases without rediscovering architectural decisions.
