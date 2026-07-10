# Quickstart — End-to-End Validation

Proves the harness gates a model correctly, front to back. Assumes the design in [plan.md](./plan.md), [data-model.md](./data-model.md), and [contracts/](./contracts/). No dataset or weights are committed — everything is fetched or generated locally (Constitution II).

## Prerequisites

- Docker (for the no-egress sandbox) and Docker Compose
- Python 3.11, Node 20
- Redis (via Compose)

## Setup

```bash
# 1. Bring up API + worker + Redis
docker compose up -d            # api:8000, worker, redis:6379

# 2. Frontend
cd frontend && npm install && npm run dev   # http://localhost:5173

# 3. Fetch a permissive stand-in dataset (NOT committed) and register it
python scripts/fetch_open_images.py --class detection --n 200   # → data/ (gitignored)
python scripts/register_golden_set.py --class detection         # POST /golden-sets

# 4. Seed a demo model + a deliberately weak model (owned/toy weights in samples/)
python scripts/seed_demo.py       # registers one healthy + one failing detector
```

## Scenario A — Healthy model passes end-to-end (US1, US3)

1. Submit via the UI (or `POST /models`) a detection model + declared sources.
2. **Expected**: status flows `pending → evaluating → approved`; Tier 1 (COCO-style mAP) ≥ threshold, Tier 2 clean+perturbed recorded separately, Tier 3 profile present.
3. Open Model Detail → **Expected**: a Model Card with populated Benchmark Results + Provenance blocks; no field blank (any unknown shows `to be confirmed`).

**Pass criteria**: SC-001 (card present), SC-009 (per-tier reasons visible).

## Scenario B — Safety-critical failure requires a human (US2, US4 — Constitution I)

1. Submit the weak model (poor minority-class recall on the stand-in).
2. **Expected**: Tier 2 per-class recall on a safety-critical class is below bar → run flagged → status `pending_adjudication`, **not** `approved`.
3. Confirm no API path approves it: `POST /adjudication/{runId}/decision` is the only way forward.
4. As reviewer, open the Adjudication Queue → evidence attached → record `reject` + rationale.
5. **Expected**: status `rejected`; an `AdjudicationRecord` (reviewer + rationale + timestamp) is stored.

**Pass criteria**: SC-002 (no auto-approval), FR-012/013.

## Scenario C — Per-class + degradation curve (US4)

1. Inspect the run's Tier 2 results.
2. **Expected**: separate scores for `clean / rain / low_light / fog`, a worst-case drop from clean, and per-class recall for safety-critical classes (not aggregate-only).

**Pass criteria**: SC-006.

## Scenario D — Reproducibility & contamination trail (Constitution IV)

1. Re-run the same model against the same Golden Test Set.
2. **Expected**: identical verdict; scores match within tolerance (research R10); each `TierResult` carries the golden-set `checksum`.

**Pass criteria**: SC-004, FR-018.

## Scenario E — Add a class without touching the harness (US6, FR-025)

1. `register_golden_set.py --class classification`, submit a classifier.
2. **Expected**: it evaluates via the registry's classification benchmark (top-1) with no engine code change.

**Pass criteria**: SC-008.

## Licensing guard (Constitution II)

```bash
pytest backend/tests/contract/test_no_restricted_data.py
# Expected: PASS — tree contains no dataset/weights; only samples/ (owned/permissive) present.
git status --porcelain data/ models/    # Expected: empty (gitignored)
```

## Test entry points (built in speckit-tasks / implement)

- `backend/tests/contract/` — API contract + no-restricted-data + no-auto-approval-path.
- `backend/tests/integration/` — Scenarios A–E as automated flows.
- `frontend/tests/` — submit + adjudication surfaces.

> Full test bodies and implementation are produced by **speckit-tasks** → **speckit-implement**, not here.
