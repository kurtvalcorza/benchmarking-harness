---
description: "Task list for Model Benchmarking Harness (POC)"
---

# Tasks: Model Benchmarking Harness (POC)

**Input**: Design documents from `specs/001-model-benchmarking-harness/`
**Prerequisites**: plan.md, spec.md, data-model.md, contracts/, research.md
**Constitution**: v1.0.0 — Principle VI requires **test-first for gating logic**; those tests are included below and MUST be written to FAIL before implementation.

**Organization**: by user story (US1–US6) for independent implementation and testing.

## Format: `[ID] [P?] [Story?] Description`
- **[P]** = parallelizable (different files, no incomplete dependency).
- **[Story]** label on user-story-phase tasks only.

---

## Phase 1: Setup (Shared Infrastructure)

- [ ] T001 Create repo structure per plan.md (`backend/{app,engine,worker,tests}`, `frontend/`, `scripts/`, `samples/`)
- [ ] T002 [P] Initialize backend Python project in `backend/pyproject.toml` (fastapi, uvicorn, sqlmodel, rq, redis, docker, torch, onnxruntime, ultralytics, timm, torchmetrics, pycocotools, imagecorruptions, albumentations, pytorch-grad-cam, jinja2, fiftyone, pytest)
- [ ] T003 [P] Initialize frontend project (Vite + React + TS) in `frontend/`
- [ ] T004 [P] `docker-compose.yml` at repo root (api, worker, redis)
- [ ] T005 [P] Sandbox base image `docker/sandbox.Dockerfile` (CV runtime for isolated runs)
- [ ] T006 [P] Linting/formatting: ruff+black (`backend/`), eslint+prettier (`frontend/`)

---

## Phase 2: Foundational (Blocking Prerequisites)

**⚠️ No user story can begin until this phase is complete.**

- [ ] T007 Define enums (ModelClass, Tier, Verdict, ModelStatus, Condition, Decision) in `backend/app/db/enums.py`
- [ ] T008 [P] SQLModel entities (Model, ModelVersion, GoldenTestSet, EvaluationRun, TierResult, ModelCard, AdjudicationRecord, AuditEvent) in `backend/app/db/models.py` per data-model.md
- [ ] T009 Append-only repository layer (reject update/delete on EvaluationRun/TierResult/AdjudicationRecord/AuditEvent) in `backend/app/db/repositories.py`
- [ ] T010 [P] Config + `thresholds.yaml` loader (unset threshold → pending_adjudication) in `backend/app/services/config.py`
- [ ] T011 FastAPI app skeleton + router wiring in `backend/app/main.py`
- [ ] T012 [P] `InferenceAdapter` Protocol per contract in `backend/engine/adapters/base.py`
- [ ] T013 [P] `BenchmarkRegistry` (class → benchmark/metric) in `backend/engine/registry/registry.py`
- [ ] T014 Docker no-egress sandbox runner (`--network none`, read-only mounts, cpu/mem/time caps, ephemeral); **all tier inference executes inside this runner** (D1) in `backend/engine/sandbox/runner.py`
- [ ] T015 [P] Metrics: mAP + per-class recall, top-k + macro-F1 in `backend/engine/metrics/`
- [ ] T016 [P] AuditEvent logging helper in `backend/app/services/audit.py`
- [ ] T017 RQ worker entrypoint in `backend/worker/main.py`
- [ ] T018 [P] Frontend app shell + routing + typed API client (from `contracts/openapi.yaml`) in `frontend/src/`
- [ ] T019 [P] **[test-first]** Contract test: no auto-approval path exists in `backend/tests/contract/test_no_auto_approval.py` (write to FAIL)
- [ ] T020 [P] **[test-first]** Contract test: tree contains no restricted datasets/weights in `backend/tests/contract/test_no_restricted_data.py` (write to FAIL)
- [ ] T021 ModelVersion state machine (transitions per data-model.md; only edge into `approved` from a flagged run is via AdjudicationRecord) in `backend/app/services/state_machine.py` → makes T019 pass

**Checkpoint**: foundation ready — stories can begin.

---

## Phase 3: User Story 1 — Automated three-tier evaluation (Priority: P1) 🎯 MVP

**Goal**: model in → automatic three-tier evaluation → verdict out.
**Independent Test**: submit one supported model; confirm auto-run, a stored result per tier, and an overall verdict, with per-tier failure reasons visible.

- [ ] T022 [P] [US1] **[test-first]** Contract test `POST /models` + auto-trigger in `backend/tests/contract/test_models_api.py` (FAIL first)
- [ ] T023 [P] [US1] **[test-first]** Integration test: healthy model → approved (quickstart Scenario A) in `backend/tests/integration/test_eval_flow.py` (FAIL first)
- [ ] T024 [P] [US1] **[test-first]** Unit test: verdict vs thresholds (pass/fail/pending) in `backend/tests/unit/test_verdict.py` (FAIL first)
- [ ] T025 [P] [US1] PyTorchAdapter (Ultralytics detection + timm classification) in `backend/engine/adapters/pytorch_adapter.py`
- [ ] T026 [P] [US1] OnnxAdapter (ONNX Runtime, CPU) in `backend/engine/adapters/onnx_adapter.py`
- [ ] T027 [US1] Tier 1 capability runner (registry-selected benchmark) in `backend/engine/tiers/tier1_capability.py`
- [ ] T028 [US1] Tier 2 stress runner — clean-condition baseline in `backend/engine/tiers/tier2_stress.py`
- [ ] T029 [US1] Tier 3 ops runner (Grad-CAM visual grounding + resource profile; **robustness de-scoped for POC**, FR-022) in `backend/engine/tiers/tier3_ops.py`
- [ ] T030 [US1] Scoring engine + verdict assignment in `backend/engine/scoring.py` → makes T024 pass
- [ ] T031 [US1] Orchestrator: run tiers in order, halt-on-fail, persist results; **dispatch each tier's inference through the sandbox runner (T014, D1)** in `backend/app/services/orchestrator.py`
- [ ] T032 [US1] `POST /models` (register + upload weights + enqueue run) in `backend/app/api/models.py` → makes T022 pass
- [ ] T033 [US1] `GET /models/{id}` and `GET /runs/{runId}` in `backend/app/api/models.py`, `backend/app/api/runs.py`
- [ ] T034 [US1] Auto-trigger: enqueue RQ job on submit + on golden-set update in `backend/app/services/orchestrator.py`
- [ ] T035 [P] [US1] Submit page (upload, declare class/provenance) in `frontend/src/pages/Submit.tsx`
- [ ] T036 [P] [US1] Model Detail page (status + per-tier results) in `frontend/src/pages/ModelDetail.tsx` → makes T023 pass

**Checkpoint**: US1 fully functional and testable (MVP).

---

## Phase 4: User Story 2 — Human adjudication of safety-critical failures (Priority: P1)

**Goal**: flagged failures route to a human; no flagged model approved without a recorded decision.
**Independent Test**: force a flag; confirm `pending_adjudication`, evidence attached, and only a recorded decision moves it.

- [ ] T037 [P] [US2] **[test-first]** Integration test: flagged → pending_adjudication → reject (Scenario B) in `backend/tests/integration/test_adjudication.py` (FAIL first)
- [ ] T038 [P] [US2] **[test-first]** Contract test: `POST /adjudication/{runId}/decision` + queue in `backend/tests/contract/test_adjudication_api.py` (FAIL first)
- [ ] T039 [US2] Implement the **flag rule** (safety-critical recall < floor OR unratified threshold OR incomplete provenance → `pending_adjudication`; else fail/pass) per FR-012 in `backend/app/services/state_machine.py` + orchestrator → makes T068 pass
- [ ] T040 [US2] `GET /adjudication/queue` (with evidence refs) in `backend/app/api/adjudication.py`
- [ ] T041 [US2] `POST /adjudication/{runId}/decision` (record AdjudicationRecord, transition status; only path to approve a flagged model) in `backend/app/api/adjudication.py` → makes T037/T038 pass
- [ ] T042 [P] [US2] Adjudication Queue page in `frontend/src/pages/AdjudicationQueue.tsx`
- [ ] T043 [P] [US2] Review page (evidence + decide + rationale) in `frontend/src/pages/Review.tsx`

**Checkpoint**: US1 + US2 both work independently.

---

## Phase 5: User Story 3 — Model Card on every approval (Priority: P1)

**Goal**: every completed model has a card; missing fields marked `to be confirmed`, human sections preserved.
**Independent Test**: complete one model; confirm card has machine blocks + preserved human sections + no blank fields.

- [ ] T044 [P] [US3] **[test-first]** Unit test: card preserves human sections + marks missing as `to be confirmed` in `backend/tests/unit/test_card.py` (FAIL first)
- [ ] T045 [US3] Model Card generator (Jinja2; Benchmark Results / Provenance / Adjudication blocks; missing → `to be confirmed`) in `backend/engine/cards/generator.py` → makes T044 pass
- [ ] T046 [US3] Regenerate-without-clobber (preserve human sections across re-runs) in `backend/engine/cards/generator.py`
- [ ] T047 [US3] Surface card in `GET /models/{id}` + card view in `frontend/src/pages/ModelDetail.tsx`

**Checkpoint**: US1–US3 independently functional.

---

## Phase 6: User Story 4 — Local-context stress + per-class results (Priority: P1)

**Goal**: Tier 2 scores clean + each adverse condition separately, with per-class recall for safety-critical classes.
**Independent Test**: run Tier 2 for one model; confirm separate per-condition scores, worst-case drop, and per-class recall.

- [ ] T048 [P] [US4] **[test-first]** Integration test: per-class recall + degradation curve (Scenario C) in `backend/tests/integration/test_tier2.py` (FAIL first)
- [ ] T049 [P] [US4] Perturbation transforms (rain/low_light/fog via imagecorruptions + albumentations, applied to owned/permissive data) in `backend/engine/perturb/transforms.py`
- [ ] T050 [US4] Tier 2: run each condition separately + compute worst-case drop from clean in `backend/engine/tiers/tier2_stress.py`
- [ ] T051 [US4] Per-class recall surfacing for the manifest's **safety_critical_classes** against **recall_floors** (FR-026) in `backend/engine/metrics/` + Tier 2 → makes T048 pass
- [ ] T052 [P] [US4] Degradation-curve + per-class display in `frontend/src/pages/ModelDetail.tsx`

**Checkpoint**: the domain gate demonstrably beats aggregate-only scoring.

---

## Phase 7: User Story 5 — Performance history across resubmissions (Priority: P2)

**Goal**: full append-only history per model across versions.
**Independent Test**: submit two versions; confirm both runs returned in order, none overwritten.

- [ ] T053 [P] [US5] **[test-first]** Integration test: multi-version append-only history in `backend/tests/integration/test_history.py` (FAIL first)
- [ ] T054 [US5] `GET /models/{id}/history` in `backend/app/api/models.py` → makes T053 pass
- [ ] T055 [P] [US5] History view in `frontend/src/pages/ModelDetail.tsx`

**Checkpoint**: history queryable.

---

## Phase 8: User Story 6 — Add a class/domain without harness changes (Priority: P2)

**Goal**: register a new Golden Test Set and evaluate a compatible model with no engine code change.
**Independent Test**: register a classification golden set, submit a classifier; it evaluates via the registry.

- [ ] T056 [P] [US6] **[test-first]** Integration test: register golden set + classifier evaluates via registry (Scenario E) in `backend/tests/integration/test_extensibility.py` (FAIL first)
- [ ] T057 [US6] `POST /golden-sets` (manifest validation incl. required **safety_critical + recall_floors**, FR-026; reject `is_public=true`) in `backend/app/api/golden_sets.py` → makes T056 pass
- [ ] T058 [P] [US6] `scripts/fetch_open_images.py` + `scripts/register_golden_set.py` (permissive stand-in; nothing committed)
- [ ] T059 [US6] Golden-set-update re-evaluation trigger (FR-004) in `backend/app/services/orchestrator.py`

**Checkpoint**: all user stories independently functional.

---

## Phase 9: Polish & Cross-Cutting Concerns

- [ ] T060 [P] `scripts/seed_demo.py` (one healthy + one weak model; owned toy weights in `samples/`)
- [ ] T061 [P] Reproducibility test: same model + set → same verdict (Scenario D) in `backend/tests/integration/test_repro.py`
- [ ] T062 CI target (make/`.github/workflows`) running the no-restricted-data (T020) + no-auto-approval (T019) gates on every push
- [ ] T063 [P] `LICENSE` (MIT) + finalize `README.md`
- [ ] T064 [P] `DATASETS.md` — per-dataset licenses + fetch-not-commit instructions (Constitution II)
- [ ] T065 Sandbox hardening review (verify `--network none`, read-only mounts, caps) in `backend/engine/sandbox/runner.py`
- [ ] T066 [P] Run quickstart Scenarios A–E end-to-end and record results

---

## Post-Analyze Remediation (2026-07-10)

New tasks from the analyze pass. IDs continue after T066 (existing IDs unchanged for determinism); insertion point noted.

- [ ] T067 [P] **[test-first]** [D1] Contract test: an evaluation runs with **no network access** — a run attempting egress fails; assert `--network none` is effective, in `backend/tests/contract/test_sandbox_no_egress.py` (FAIL first). *Insert in Phase 2 (Foundational), after T014; kept green by CI (T062).*
- [ ] T068 [P] **[test-first]** [C1] Unit test: the **flag rule** (safety-critical recall < floor / unratified threshold / incomplete provenance → `pending_adjudication`; else fail/pass) in `backend/tests/unit/test_flag_rule.py` (FAIL first). *Insert in Phase 4 (US2), before T039.*

## Dependencies & Execution Order

- **Setup (P1)** → **Foundational (P2, blocks everything)** → **User Stories (P3–P8)** → **Polish (P9)**.
- **Story order**: US1 (MVP) → US2, US3, US4 (all P1; US4 extends US1's Tier 2, US2/US3 consume US1 runs) → US5, US6 (P2).
- **Within a story**: test-first tasks precede implementation; models → services → endpoints → UI.
- **Constitution gates** T019/T020 (foundational, test-first) must stay green from Phase 2 onward.

## Parallel Opportunities

- Setup: T002–T006 in parallel.
- Foundational: T008, T010, T012, T013, T015, T016, T018, T019, T020 in parallel (T009/T011/T014/T017/T021 have deps).
- Per story, `[P]` tests and adapters/UI in different files run in parallel (e.g. US1: T022/T023/T024 together; T025/T026 together; T035/T036 together).
- Once Foundational done, different developers can take US2, US3, US4 in parallel after US1 lands.

## Implementation Strategy

- **MVP = Phase 1 + 2 + US1.** Stop and validate: a model runs through three tiers and gets a verdict (quickstart Scenario A). Demo-able.
- **Then P1 completion**: add US2 (the non-negotiable human gate), US3 (cards), US4 (the per-class domain value) — each independently testable.
- **Then P2**: US5, US6.
- **Leaner first cut (if scope bites)**: implement US1 with a CLI trigger before the React surfaces (T035/T036 → a thin CLI), or detection-only (skip classification registry entry) — both pre-agreed trims.

## Notes

- Test-first tasks are limited to gating logic (Constitution VI), not blanket coverage.
- Every task names a file path; `[P]` only where files don't overlap.
- No restricted datasets/weights are ever committed (T020 enforces; Constitution II).
