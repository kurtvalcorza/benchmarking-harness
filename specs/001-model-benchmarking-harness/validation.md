# Quickstart Validation Record (T066) — 2026-07-10

Environment: offline demo mode (`HARNESS_EVAL_MODE=inline`,
`HARNESS_SANDBOX_MODE=subprocess`), stub framework, owned synthetic sample
data. All five scenarios also run as automated tests on every push (CI).

| Scenario | Result | Evidence |
|---|---|---|
| **A** — healthy model end-to-end | ✅ `pending → evaluating → approved`; Tier 1 mAP 0.852 ≥ 0.25; Tier 2 clean + rain/low_light/fog scored separately; Tier 3 grounding 0.82 + resource profile; card populated, `missing_fields=[]` | live run via `scripts/seed_demo.py`; `backend/tests/integration/test_eval_flow.py` |
| **B** — safety-critical failure needs a human | ✅ weak model flagged (`safety_critical_recall_below_floor`), status `pending_adjudication`, never approved; evidence refs attached in queue; recorded `reject` decision (reviewer + rationale + timestamp) moved it to `rejected` and onto the card | live run; `backend/tests/integration/test_adjudication.py`, `tests/contract/test_adjudication_api.py` |
| **C** — per-class + degradation curve | ✅ separate scores per condition; worst-case drop 0.0662 under `low_light`; per-class pedestrian recall vs floor surfaced for every condition | `backend/tests/integration/test_tier2.py` |
| **D** — reproducibility & contamination trail | ✅ identical verdict and scores across re-runs (exact match, timing metrics excluded); golden-set checksum stamped on every Tier-2 result | `backend/tests/integration/test_repro.py` |
| **E** — add a class without touching the harness | ✅ classification golden set registered via manifest; classifier evaluated through the registry (ImageNet-top-1 slot); no engine change | `backend/tests/integration/test_extensibility.py` |
| Licensing guard | ✅ `pytest backend/tests/contract/test_no_restricted_data.py` PASS; tracked tree contains only owned synthetic samples | CI `constitution-gates` job |
| No-egress (D1) | ✅ runtime assertion + subprocess guard verified; docker config asserts `network_disabled`, read-only mounts, cpu/mem/pids caps | `backend/tests/contract/test_sandbox_no_egress.py` |

Suite status at record time: **backend 63 passed; frontend build + tests green; ruff/eslint clean.**

Deviations from quickstart assumptions:
- Docker daemon was unavailable in the validation environment, so the sandbox
  ran in `subprocess` fallback mode (socket-guard + runtime no-egress
  assertion). The docker path's hardening config is unit-asserted; T065's
  checklist (`--network none`, read-only mounts, caps) is encoded in
  `docker_container_config()` and its test.
- Real Open Images fetching (`scripts/fetch_open_images.py`) requires the `ml`
  extra + network; validation used the owned synthetic stand-ins via
  `--synthetic` layout (same manifest/dataset contract).
