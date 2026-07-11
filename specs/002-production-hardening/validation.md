# Validation Record: Production Hardening (Feature 002)

Running record of validation evidence produced during implementation. Extended by
the cross-cutting validation tasks (T082–T085).

## T002 — Vite/Vitest advisory remediation

The Feature 001 frontend toolchain carried known esbuild/vite/vitest advisories
(`npm audit`: 3 moderate, 1 high, 1 critical). Upgraded to supported releases and
regenerated `package-lock.json`.

Resolved versions (local, Node 24 / npm 11; CI Node 22):

| Package | Was | Now |
|---|---|---|
| `vite` | ^5.4.0 | ^7.0.0 (resolved 7.3.6) |
| `vitest` | ^2.0.0 | ^3.2.6 (resolved 3.2.7) |
| `@vitejs/plugin-react` | ^4.3.1 | ^5.0.0 |

Post-upgrade checks (local):

- `npm audit --audit-level=high` → **found 0 vulnerabilities**
- `npm run build` → built in ~0.5s (vite 7.3.6)
- `npm test` → 1 file / 1 test passed (vitest 3.2.7)
- `npm run lint` → clean

The remaining moderate advisories from Feature 001 are absent.

## T083 — FR-001..FR-030 traceability

Every functional requirement maps to implementing code and at least one test. No
unresolved gaps.

| FR | Implementation | Test evidence |
|---|---|---|
| FR-001 auth on all non-health routes | `app/api/auth.py` (`get_principal`/`require_roles`), `app/main.py` | `tests/contract/test_authorization.py` |
| FR-002 token validation + fail-closed prod | `app/services/auth.py`, `app/services/config.py::_validate` | `tests/unit/test_auth_tokens.py`, `tests/unit/test_config.py` |
| FR-003 role authorization | `app/api/auth.py`, `contracts/security-boundary.md` | `tests/contract/test_authorization.py` |
| FR-004 identity from principal (not body) | `app/api/adjudication.py` (`reviewer=principal.subject`), `schemas.py` | `tests/contract/test_adjudication_identity.py` |
| FR-005 audit telemetry, no raw tokens | `app/services/audit.py`, route handlers | `tests/integration/test_security_audit.py` |
| FR-006 bounded/hashed/atomic upload | `app/services/artifact_ingest.py` | `tests/contract/test_upload_limits.py` |
| FR-007 no partial artifact; 413 | `app/api/models.py`, `artifact_ingest.py` | `tests/integration/test_artifact_ingest_failures.py` |
| FR-008 upload limit documented+exposed | `/readyz` `upload_limit_bytes`, `README.md`, `docker-compose.yml` | `tests/contract/test_upload_limits.py` |
| FR-009 classification coverage (missing=incorrect) | `engine/metrics/coverage.py`, `classification.py` | `tests/unit/test_classification_coverage.py` |
| FR-010 finite/shape validation pre-metric | `engine/metrics/coverage.py` | `tests/unit/test_prediction_validation.py` |
| FR-011 pinned COCO; approximation renamed | `engine/metrics/detection.py` | `tests/unit/test_detection_coco.py` |
| FR-012 coverage + evaluator provenance | tier scorers + `orchestrator._persist_tier_results` | `tests/unit/test_detection_coco.py`, `tests/integration/test_metric_integrity.py` |
| FR-013 atomic completion | `app/services/orchestrator.py::evaluate_version` | `tests/integration/test_atomic_completion.py` |
| FR-014 atomic adjudication | `app/api/adjudication.py` | `tests/integration/test_atomic_adjudication.py` |
| FR-015 card from transaction-local inputs | `orchestrator._upsert_card` | `tests/integration/test_atomic_completion.py` |
| FR-016 durable intents in submission/re-eval txn | `app/services/jobs.py`, `api/models.py`, `orchestrator.py` | `tests/integration/test_durable_dispatch.py` |
| FR-017 dispatcher retry + idempotent claim | `app/services/dispatcher.py`, `jobs.py` | `tests/integration/test_job_claims.py`, `test_durable_dispatch.py` |
| FR-018 queue outage: no re-submit | `api/models.py` best-effort dispatch | `tests/integration/test_durable_dispatch.py` |
| FR-019 no confidence-derived grounding | `engine/tiers/tier3_ops.py` (proxy removed) | `tests/integration/test_tier3_grounding.py` |
| FR-020 measured grounding evidence | `engine/metrics/grounding.py` | `tests/unit/test_grounding_evidence.py` |
| FR-021 unavailable routes; no silent pass | `tier3_ops.py`, `grounding.py` | `tests/integration/test_tier3_grounding.py` |
| FR-022 migrations + PostgreSQL | `backend/migrations/`, `app/services/config.py` | `tests/migration/test_upgrade.py` |
| FR-023 schema-revision check; create_all limited | `app/db/repositories.py`, `schema_check.py` | `tests/contract/test_schema_readiness.py` |
| FR-024 sandbox hardening | `engine/sandbox/runner.py`, `docker/sandbox-seccomp.json` | `tests/contract/test_sandbox_hardening.py`, `tests/integration/test_sandbox_runtime.py` (live) |
| FR-025 isolated runner boundary | `backend/runner/main.py`, `runner_client.py`, `docker-compose.yml` | `docs/security/threat-model.md`; live probes |
| FR-026 pinned images/actions; locked builds | `.github/workflows/*.yml`, `docker/*.Dockerfile`, lockfiles | CI |
| FR-027 dependency scan (high/critical) | `.github/workflows/ci.yml` (`pip-audit`, `npm audit --audit-level=high`) | CI; `docs/security/advisory-exception.md` |
| FR-028 supported Vite/Vitest; no reviewer text | `frontend/`, `package.json` | `frontend/tests/review.test.tsx`, `submit.test.tsx` |
| FR-029 tests written to fail first | every `[test-first]` task | observed failing pre-impl (this record + commits) |
| FR-030 Constitution gates remain green | `make gates` | `tests/contract/test_no_restricted_data.py`, `test_no_auto_approval.py`, `test_sandbox_no_egress.py` |

## T082 — Quickstart scenario validation

The `quickstart.md` scenarios are exercised as follows (offline/CI-runnable
coverage in the suite; the production Compose profile is the operator path):

| Quickstart step | How validated |
|---|---|
| 1 Install reproducibly | `pip install` from locked deps; CI dependency gate green |
| 2 Migrate (PostgreSQL) | `tests/migration/test_upgrade.py` (empty + baseline) — CI Postgres job green |
| 3 Local identities | `scripts/dev_token.py` + `mint_dev_token`; refuses in production |
| 5 Bounded upload (413/415/507) | `tests/contract/test_upload_limits.py`, `tests/integration/test_artifact_ingest_failures.py` |
| 6 Queue-outage recovery | `tests/integration/test_durable_dispatch.py` (broker outage + dispatcher recovery) |
| 7 Metric coverage | `tests/unit/test_classification_coverage.py`, `test_prediction_validation.py`, `tests/integration/test_metric_integrity.py` |
| 8 Atomic completion + adjudication | `tests/integration/test_atomic_completion.py`, `test_atomic_adjudication.py` |
| 9 Grounding semantics | `tests/integration/test_tier3_grounding.py` (confidence-only, insufficient-sample, poorly-grounded) |
| 10 Sandbox controls | `tests/contract/test_sandbox_hardening.py` + `tests/integration/test_sandbox_runtime.py` — **live probes ran on a real Docker daemon: non-root UID 65532, network unreachable, read-only root fs, writable out-mount — 4/4 pass** |
| 11 All gates | see T085 below |

## T084 — Spec Kit cross-artifact analysis

Cross-checked `spec.md` (FR-001..030), `plan.md`, `data-model.md`, `contracts/`
(openapi, security-boundary, metric-evidence, inference-adapter), and `tasks.md`.

- Entities in `data-model.md` (ArtifactReceipt, JobIntent, JobAttempt, coverage/
  evaluator/evidence_digest, audit identity, GroundingEvidence) all exist in
  `app/db/models.py` and `engine/metrics/grounding.py`.
- `contracts/metric-evidence.md` metric identity (`coco_ap_50_95`, `coco_ap_50`,
  `map_50_95` alias, `diagnostic_precision_recall_product`) matches
  `engine/metrics/detection.py`; the GroundingEvidence field set matches
  `grounding.py::GroundingEvidence.to_dict()`.
- `contracts/openapi.yaml` validates (`openapi-spec-validator` exit 0) and the
  security-boundary role matrix matches `app/api/auth.py`.
- `tasks.md` T001–T085 reconciled to the implementation; all story tasks ticked.

**Resolved during implementation** (no longer open): grounding `evidence_ref`
made content-addressed (was a non-resolvable `sha256:` URI); per-run `run_id` in
grounding metrics removed to preserve SC-004 reproducibility. **Zero unresolved
critical inconsistencies.**

## T085 — Final gate command record

Commands run on this branch (`docs/002-phase9`), real exit codes captured
(`; echo "exit=$?"`, not a grepped summary):

| Gate | Command | Result |
|---|---|---|
| Backend suite | `pytest -q` | **PYTEST_EXIT=0** (all pass) |
| Frontend tests | `npm test` | exit 0 — 9 passed |
| Frontend build | `npm run build` | exit 0 |
| Frontend lint | `npm run lint` | exit 0 |
| Node advisories (FR-027) | `npm audit --audit-level=high` | exit 0 — 0 high/critical |
| Lint (backend) | `ruff check .` | exit 0 |
| Constitution gates (I/II/IV) | `pytest test_no_restricted_data + test_no_auto_approval + test_sandbox_no_egress` | exit 0 |
| OpenAPI contract | `openapi-spec-validator contracts/openapi.yaml` | exit 0 |
| Live sandbox probes (T069) | `pytest tests/integration/test_sandbox_runtime.py` | exit 0 — 4/4 on a live Docker daemon |
| Migrations (empty + baseline) | CI Postgres job | green |
| Python advisories (FR-027) | CI `pip-audit` (pinned deps) | green (CI dependency+spec gate) |

Note: local `pip-audit` against the full `[ml]` dev venv (torch/onnx/etc.) is not
the FR-027 gate; the gate scans the pinned production/dev dependency set in CI,
which is green.

