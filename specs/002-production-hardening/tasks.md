---
description: "Test-first implementation tasks for production hardening and evaluation integrity"
---

# Tasks: Production Hardening and Evaluation Integrity

**Input**: Design documents from `/specs/002-production-hardening/`

**Prerequisites**: `spec.md`, `plan.md`, `research.md`, `data-model.md`, `contracts/`, `quickstart.md`

**Tests**: Mandatory. Constitution VI and FR-029 require tests to be written and observed failing before gating/security/durability implementation.

**Format**: `[ID] [P?] [Story] Description with exact file paths`

## Phase 1: Setup and reproducibility

**Purpose**: Establish locked dependencies, configuration, and CI scaffolding used by all stories.

- [x] T001 Add Python production/dev/security dependencies and generate a reproducible `uv.lock` from `backend/pyproject.toml` and repository root configuration
- [x] T002 [P] Upgrade supported Vite/Vitest and regenerate `frontend/package-lock.json`; record resolved versions in `specs/002-production-hardening/validation.md`
- [x] T003 [P] Add typed environment configuration (environment, auth, upload, DB, queue, runner, grounding) in `backend/app/services/config.py`
- [x] T004 [P] Add configuration unit tests, including production fail-closed combinations, in `backend/tests/unit/test_config.py`
- [x] T005 Add `pip-audit`, `npm audit --audit-level=high` (the FR-027 high/critical gate, not bare `npm audit`), lockfile verification, OpenAPI validation, and migration tests to `.github/workflows/ci.yml` and `Makefile`
- [x] T006 Pin GitHub Actions to immutable SHAs with release comments in `.github/workflows/ci.yml`, `.github/workflows/claude.yml`, and `.github/workflows/claude-code-review.yml`
- [x] T007 Pin API/sandbox base images and install from locked inputs in `docker/api.Dockerfile` and `docker/sandbox.Dockerfile`

**Checkpoint**: clean installs are reproducible and security gates exist before feature behavior changes.

---

## Phase 2: Foundational storage, migrations, and identity

**Purpose**: Blocking prerequisites for every user story.

- [x] T008 [P] **[test-first]** Add empty-database and Feature 001 baseline migration tests in `backend/tests/migration/test_upgrade.py`
- [x] T009 [P] **[test-first]** Add production stale/unknown-schema startup tests in `backend/tests/contract/test_schema_readiness.py`
- [x] T010 Configure Alembic in `backend/alembic.ini`, `backend/migrations/env.py`, and `backend/migrations/script.py.mako`
- [x] T011 Create Feature 001 baseline migration in `backend/migrations/versions/0001_feature_001_baseline.py`
- [x] T012 Extend SQLModel entities for receipts, coverage/evaluator fields, job intents/attempts, and audit identity in `backend/app/db/models.py`
- [x] T013 Create Feature 002 schema/backfill migration in `backend/migrations/versions/0002_production_hardening.py`
- [x] T014 Replace production `create_all` startup with schema-revision checks while preserving explicit ephemeral-test setup in `backend/app/db/repositories.py`, `backend/app/main.py`, and `backend/app/services/schema_check.py`
- [x] T014a Add the `postgres` service and a `production` Compose profile (grouping `postgres`, `redis`, and the runner boundary added in T073) to `docker-compose.yml` and `.env.example`, so the migration and outage validation commands in `quickstart.md` are runnable
- [x] T015 [P] Add PostgreSQL test fixtures and transactional cleanup in `backend/tests/conftest_postgres.py`
- [x] T016 [P] **[test-first]** Add JWT issuer/audience/algorithm/time/JWKS rotation tests in `backend/tests/unit/test_auth_tokens.py`
- [x] T017 [P] **[test-first]** Add endpoint `401`/`403` role-matrix tests in `backend/tests/contract/test_authorization.py`
- [x] T018 Implement typed `Principal`, OIDC discovery/JWKS cache, token validation, and role mapping in `backend/app/services/auth.py`
- [x] T019 Implement FastAPI bearer/role/object-authorization dependencies in `backend/app/api/auth.py`
- [x] T020 Protect all non-health routers and add authenticated readiness in `backend/app/main.py`, `backend/app/api/models.py`, `backend/app/api/runs.py`, `backend/app/api/golden_sets.py`, and `backend/app/api/adjudication.py`
- [x] T020a **[test-first]** Reject Golden Set registration whose `data_ref` does not resolve beneath the configured data/sample roots (path containment after symlink resolution, `422`) in `backend/app/api/golden_sets.py`, with tests in `backend/tests/contract/test_golden_set_path_containment.py` — enforce at registration, not only in the runner (T072)
- [x] T020b Add the governance/auditor-scoped `GET /golden-sets/{id}` re-evaluation-status read (object-scoped to the requester's own registrations) in `backend/app/api/golden_sets.py`, with authorization tests in `backend/tests/contract/test_authorization.py`
- [x] T021 Propagate authenticated actor/issuer/request ID into sanitized audit records in `backend/app/services/audit.py` and route handlers
- [x] T022 Add explicit dev-token helper and production-mode refusal in `scripts/dev_token.py` and `backend/tests/contract/test_dev_auth_refusal.py`

**Checkpoint**: migrated storage and verified principals are available; all protected routes fail closed.

---

## Phase 3: User Story 1 - Authorized lifecycle operations (Priority: P1) MVP

**Goal**: Users perform only role-authorized operations and permanent records use verified identity.

**Independent Test**: Role-matrix contract suite plus an adjudication verifying token subject overrides/rejects any supplied reviewer field.

- [x] T023 [P] [US1] **[test-first]** Add submitter ownership read tests in `backend/tests/contract/test_model_access.py`
- [x] T024 [P] [US1] **[test-first]** Add authenticated adjudicator identity and forbidden `reviewer` property tests in `backend/tests/contract/test_adjudication_identity.py`
- [x] T025 [US1] Persist `submitted_by` and enforce own-object reads in `backend/app/api/models.py`, `backend/app/api/runs.py`, and `backend/app/db/models.py`
- [x] T026 [US1] Remove reviewer from `DecisionIn`, derive it from `Principal`, and atomically record issuer/subject in `backend/app/api/schemas.py` and `backend/app/api/adjudication.py`
- [x] T027 [US1] Require governance/adjudicator/auditor permissions according to `contracts/security-boundary.md` in all API handlers
- [x] T028 [US1] Add allowed/denied lifecycle audit assertions in `backend/tests/integration/test_security_audit.py`

**Checkpoint**: no client can self-assert reviewer identity or cross role/object boundaries.

---

## Phase 4: User Story 2 - Complete and standards-based metrics (Priority: P1)

**Goal**: Every expected item is accounted for and COCO-named detection metrics use the reference evaluator.

**Independent Test**: Incomplete/duplicate/invalid classification and detection batches plus direct reference comparison.

- [x] T029 [P] [US2] **[test-first]** Add complete/missing/duplicate/unexpected classification fixtures in `backend/tests/unit/test_classification_coverage.py`
- [x] T030 [P] [US2] **[test-first]** Add NaN/infinite/malformed prediction validation tests in `backend/tests/unit/test_prediction_validation.py`
- [ ] T031 [P] [US2] **[test-first]** Add deterministic direct-COCO reference comparison fixtures in `backend/tests/unit/test_detection_coco.py`
- [x] T032 [US2] Implement reusable prediction coverage/shape validation and typed issue codes in `backend/engine/metrics/coverage.py`
- [x] T033 [US2] Rewrite classification evaluation around expected annotation IDs and missing-as-incorrect semantics in `backend/engine/metrics/classification.py`
- [ ] T034 [US2] Replace COCO-named detection approximation with pinned pycocotools evaluation and deterministically mapped inputs in `backend/engine/metrics/detection.py`
- [ ] T035 [US2] Rename any retained lightweight diagnostic metric and migrate thresholds/cards from ambiguous `map_50_95` naming in `backend/thresholds.yaml`, `backend/engine/scoring.py`, and `backend/engine/cards/templates/model_card.md.j2`
- [x] T036 [US2] Add coverage/evaluator provenance to `TierOutcome`, Tier 1, Tier 2, persistence, and API schemas in `backend/engine/tiers/tier1_capability.py`, `backend/engine/tiers/tier2_stress.py`, `backend/app/services/orchestrator.py`, and `backend/app/api/schemas.py`
- [ ] T037 [US2] Display coverage discrepancies and evaluator identity in `frontend/src/pages/ModelDetail.tsx` and add tests in `frontend/tests/model-detail.test.tsx`
- [x] T038 [US2] Add end-to-end regression proving omitted predictions cannot improve a verdict in `backend/tests/integration/test_metric_integrity.py`

**Checkpoint**: metric names, denominators, and evaluator evidence are defensible and reproducible.

---

## Phase 5: User Story 3 - Bounded atomic uploads (Priority: P1)

**Goal**: Valid large artifacts stream safely; oversized/interrupted inputs leave no state.

**Independent Test**: below/exactly/above limit and interrupted-stream contract tests with filesystem/database cleanup assertions.

- [x] T039 [P] [US3] **[test-first]** Add upload boundary and digest tests in `backend/tests/contract/test_upload_limits.py`
- [x] T040 [P] [US3] **[test-first]** Add cancellation, disk-full, invalid-extension, and cleanup tests in `backend/tests/integration/test_artifact_ingest_failures.py`
- [x] T041 [US3] Implement chunk-counted hashing, `.part` cleanup, type validation, and atomic finalization in `backend/app/services/artifact_ingest.py`
- [x] T042 [US3] Refactor `POST /models` to use ArtifactReceipt and create domain state only on successful finalization in `backend/app/api/models.py`
- [x] T043 [US3] Add abandoned temporary-file janitor with root containment in `backend/app/services/artifact_janitor.py`
- [x] T044 [US3] Surface `413`/`415`/`507`, receipt metadata, and upload limit diagnostics through `backend/app/api/schemas.py`, `backend/app/main.py`, and `specs/002-production-hardening/contracts/openapi.yaml`
- [x] T045 [US3] Configure matching Compose/reverse-proxy upload limit guidance in `docker-compose.yml`, `.env.example`, and `README.md`

**Checkpoint**: actual streamed bytes are bounded and no partial artifact can become evaluable.

---

## Phase 6: User Story 4 - Atomic completion and durable work (Priority: P1)

**Goal**: Lifecycle/card evidence commits atomically and queue outages/redelivery do not lose or duplicate work.

**Independent Test**: Fault injection at card/evidence/commit/dispatch boundaries and duplicated job delivery.

- [ ] T046 [P] [US4] **[test-first]** Add evaluation card-render/evidence/commit fault tests in `backend/tests/integration/test_atomic_completion.py`
- [ ] T047 [P] [US4] **[test-first]** Add adjudication card-render/commit fault tests in `backend/tests/integration/test_atomic_adjudication.py`
- [ ] T048 [P] [US4] **[test-first]** Add Redis outage/recovery and duplicate-delivery tests in `backend/tests/integration/test_durable_dispatch.py`
- [ ] T049 [P] [US4] **[test-first]** Add concurrent dispatcher/worker claim tests against PostgreSQL in `backend/tests/integration/test_job_claims.py`
- [ ] T050 [US4] Refactor Model Card generation to render from explicit transaction-local inputs in `backend/engine/cards/generator.py`
- [ ] T051 [US4] Add temporary evidence staging, digesting, atomic publish, and compensation in `backend/app/services/evidence_store.py`
- [ ] T052 [US4] Refactor evaluation completion into one database transaction for run/tiers/status/audit/card/job in `backend/app/services/orchestrator.py`
- [ ] T053 [US4] Refactor adjudication into one transaction for decision/status/audit/card in `backend/app/api/adjudication.py`
- [ ] T054 [US4] Implement JobIntent creation/idempotency repository operations in `backend/app/db/repositories.py` and `backend/app/services/jobs.py`
- [ ] T055 [US4] Create evaluation intents in submission, Golden Set registration, and mid-run staleness flows in `backend/app/api/models.py`, `backend/app/api/golden_sets.py`, and `backend/app/services/orchestrator.py`
- [ ] T056 [US4] Implement PostgreSQL leased outbox dispatcher with retry/backoff in `backend/app/services/dispatcher.py`
- [ ] T057 [US4] Update RQ worker to claim/finalize intents idempotently and make duplicate delivery a no-op in `backend/worker/main.py`
- [ ] T058 [US4] Route inline test/demo execution through the same intent/claim code in `backend/app/services/jobs.py`
- [ ] T059 [US4] Add orphaned-evidence and stuck-intent operational diagnostics in `backend/app/services/reconciliation.py` and authenticated readiness output

**Checkpoint**: no dual-write queue gap and no completed/approved state without its current card.

---

## Phase 7: User Story 5 - Defensible Tier 3 evidence (Priority: P1)

**Goal**: Grounding is measured from reproducible labeled localization evidence or explicitly unavailable.

**Independent Test**: Valid evidence passes; confidence-only, scalar-only, malformed, and insufficient evidence cannot pass.

- [ ] T060 [P] [US5] **[test-first]** Add GroundingEvidence schema/validation cases in `backend/tests/unit/test_grounding_evidence.py`
- [ ] T061 [P] [US5] **[test-first]** Add confidence-only and insufficient-sample Tier 3 regressions in `backend/tests/integration/test_tier3_grounding.py`
- [ ] T062 [US5] Add typed attribution/grounding output contract to `backend/engine/adapters/base.py` and `backend/engine/sandbox/job.py`
- [ ] T063 [US5] Implement approved-method registry and pointing-game/energy localization evaluator in `backend/engine/metrics/grounding.py`
- [ ] T064 [US5] Remove confidence-coverage fallback and enforce measured/unavailable semantics in `backend/engine/tiers/tier3_ops.py`
- [ ] T065 [US5] Update stub fixtures/adapters to emit reproducible evidence objects rather than an unverified scalar in `backend/engine/adapters/stub_adapter.py` and `samples/models/*.stub.json`
- [ ] T066 [US5] Record grounding method/sample/target/evidence in Tier 3 evidence and Model Cards in `backend/app/services/orchestrator.py` and `backend/engine/cards/templates/model_card.md.j2`
- [ ] T067 [US5] Show measured versus unavailable grounding explicitly in `frontend/src/pages/ModelDetail.tsx` and `frontend/tests/model-detail.test.tsx`

**Checkpoint**: confidence is never represented or thresholded as interpretability.

---

## Phase 8: User Story 6 - Safe operations and sandboxing (Priority: P2)

**Goal**: Production deployment uses migrated storage, reproducible inputs, hardened isolation, and supported frontend dependencies.

**Independent Test**: Fresh/baseline migration, malicious sandbox probe, dependency gates, and authenticated browser flow.

- [x] T068 [P] [US6] **[test-first]** Extend sandbox config assertions for user/capabilities/no-new-privileges/seccomp/mount roots in `backend/tests/contract/test_sandbox_hardening.py`
- [ ] T069 [P] [US6] **[test-first]** Add live runtime probes for UID/capabilities/write/network/PID/memory/timeout controls in `backend/tests/integration/test_sandbox_runtime.py`
- [x] T070 [US6] Add non-root sandbox user, pinned dependencies, and minimal writable paths in `docker/sandbox.Dockerfile`
- [x] T071 [US6] Add `cap_drop=ALL`, no-new-privileges, seccomp, non-root user, bounded tmpfs/output, and effective-config evidence in `backend/engine/sandbox/runner.py` and `docker/sandbox-seccomp.json`
- [ ] T072 [US6] Validate artifact/dataset/output paths against allowlisted resolved roots in `backend/engine/sandbox/runner.py`
- [ ] T073 [US6] Separate runtime authority into a dedicated runner service/rootless-or-proxy boundary in `docker-compose.yml`, `backend/app/services/runner_client.py`, and `backend/runner/main.py`
- [ ] T074 [US6] Ensure API/general worker containers have no unrestricted runtime socket and document production runner requirements in `README.md` and `specs/002-production-hardening/quickstart.md`
- [x] T075 [P] [US6] Add browser OIDC provider/session handling and bearer API client in `frontend/src/auth/`, `frontend/src/api/client.ts`, and `frontend/src/main.tsx`
- [x] T076 [P] [US6] Remove free-text reviewer UI and display verified signed-in identity in `frontend/src/pages/Review.tsx` and `frontend/tests/review.test.tsx`
- [x] T077 [US6] Add role-aware routes and authorization error states in `frontend/src/main.tsx`, `frontend/src/pages/Submit.tsx`, and `frontend/src/pages/AdjudicationQueue.tsx`

**Checkpoint**: production-like operation passes migration, auth, dependency, and runtime isolation checks.

---

## Phase 9: Cross-cutting validation and documentation

- [ ] T078 [P] Update API and operator documentation in `README.md`, `DATASETS.md`, and `specs/002-production-hardening/contracts/openapi.yaml`
- [ ] T079 [P] Add Feature 002 threat model and advisory exception template in `docs/security/threat-model.md` and `docs/security/advisory-exception.md`
- [ ] T080 Create a Feature 001 database migration dry-run/rollback runbook in `docs/operations/migrations.md`
- [ ] T081 Create queue outage, stuck intent, evidence reconciliation, and runner outage runbook in `docs/operations/recovery.md`
- [ ] T082 Run all quickstart scenarios and record exact results in `specs/002-production-hardening/validation.md`
- [ ] T083 Generate FR-001..FR-030 -> tests/tasks traceability and resolve every gap in `specs/002-production-hardening/validation.md`
- [ ] T084 Run Spec Kit cross-artifact analysis against `spec.md`, `plan.md`, `data-model.md`, `contracts/`, and `tasks.md`; record zero unresolved critical inconsistencies in `specs/002-production-hardening/validation.md`
- [ ] T085 Run all backend/frontend/Constitution/dependency/migration/sandbox gates and attach the final command record to `specs/002-production-hardening/validation.md`

## Dependencies & execution order

- Phase 1 and Phase 2 block all user stories.
- US1 depends on identity foundation.
- US2 and US3 can proceed independently after Phase 2.
- US4 depends on migrations/entities and should land before adapting all callers in US5/US6.
- US5 depends on US2 evaluator provenance and US4 atomic evidence persistence.
- US6 depends on the configuration/storage foundation; frontend authentication depends on US1's API contract.
- Cross-cutting validation follows all selected stories.

## Parallel opportunities

- `[P]` tasks touch different files or independent test surfaces.
- After Phase 2, separate developers can take US1, US2, and US3.
- Within US4, atomicity tests, dispatch tests, and PostgreSQL claim tests can be authored in parallel before implementation.
- Sandbox backend work and frontend OIDC work can proceed in parallel during US6.

## MVP strategy

The smallest safe increment is Phase 1 + Phase 2 + US1 + US2 + US3. It closes unauthorized governance, score inflation, and disk-exhaustion exposure. It does **not** claim production readiness until US4 atomicity/durability, US5 evidence validity, and US6 sandbox/migration operations are complete.

## Notes

- Check tasks only after the named validation passes.
- Tests must be observed failing before corresponding implementation.
- Never weaken a Constitution gate to make a new test pass.
- Do not commit tokens, restricted datasets, production weights, database dumps, or generated runtime evidence.
