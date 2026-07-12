---
description: "Tasks for real-model visual grounding (Tier 3 attribution for detection)"
---

# Tasks: Real-Model Visual Grounding for Tier 3

**Input**: `specs/004-real-model-grounding/spec.md`

**Prerequisites**: `spec.md`, `plan.md`, `research.md`, `data-model.md`,
`contracts/grounding-attribution.md`, `quickstart.md` (this Phase-0 set).

**Tests**: Mandatory. Constitution VI / FR-313 require the saliency/math, pointing-game,
canonicalization, and timing-exclusion tests written and observed failing before impl.

**Format**: `[ID] [P?] [Story] Description with exact file paths`. `[x]` = delivered; `[ ]` = to build.

## Phase 0 — Design (before code) — ✅ DONE (this artifact set)

- [x] T100 [US1] `scoping.md` + `spec.md`: problem grounded in `_predict_det`/`tier3_ops`; four decisions locked (D-RISE+Grad-CAM, on-by-default, point+energy, detection-only)
- [x] T101 [US1] `plan.md` + `research.md` (R1–R7): method choice, timing separation, canonicalization fix, determinism seeding, budget
- [x] T102 [US1] `data-model.md` + `contracts/grounding-attribution.md`: attribution entry shape, extractor contract, determinism/timing/budget/provenance; no persisted schema change
- [x] T103 [US2] `quickstart.md` + `checklists/requirements.md`

## Phase 1 — Tests first (observed failing before impl — FR-313)

- [ ] T110 [P] [US1] D-RISE unit tests: seeded-mask **determinism** (same seed → same map/point/energy), `peak→point` and `energy_inside` math, saliency shape/finiteness — `backend/tests/unit/test_grounding_drise.py`
- [ ] T111 [P] [US2] Attribution **canonicalization** guard: a `person` attribution scored against a benchmark dataset whose `manifest.label_map` is `{person: pedestrian}` → pointing-game **hit** inside the pedestrian box; without canon → miss. The test MUST assert canonicalization uses the **Tier-3 benchmark dataset's** manifest map (not a Golden Set map), so it actually guards the real seam — `backend/tests/unit/test_grounding_canon.py`
- [ ] T112 [P] [US1] Pointing-game **hit/miss** on a synthetic 2-box fixture (attend-right → hit, attend-wrong → miss), score matches a hand computation — `backend/tests/unit/test_grounding_drise.py`
- [ ] T113 [US4] Integration: a detection run with the explainer on reports `grounding.status == "measured"` (sample_count ≥ min) AND `latency_ms_per_image`/`edge_profile` equal the clean pass (explain **excluded**) — `backend/tests/integration/test_tier3_real_grounding.py`
- [ ] T114 [US1] Live sandbox grounding probe: real `yolov8n.pt` emits D-RISE attribution inside `--network none`; attribution survives the `result.json` boundary — `backend/tests/integration/test_sandbox_runtime.py` (`importorskip`; real run [HW])
- [ ] T115 [US5] Provenance surfacing test (FR-311, per @claude review): a measured Tier-3 result's tier metrics + Model Card row carry the extractor (`drise`/`gradcam`), `evaluator_version`, `sample_count`, and a resolvable `evidence_ref` whose sha256 == `evidence_digest` — a light assertion so the US5 surfacing isn't the one FR without a test

## Phase 2 — D-RISE extractor + adapter explain step (US1)

- [ ] T120 [US1] `engine/metrics/grounding_drise.py`: seeded low-res mask generator (seed = `sha256(weights_digest|image_id)` + `HARNESS_DRISE_SEED`), masked-inference weighting `IoU·cos·objectness`, saliency accumulation, `peak` + `energy_inside` reduction (FR-301/302/303)
- [ ] T121 [US1] `engine/adapters/pytorch_adapter.py` `_predict_det`: opt-in **explain** step appends `{label, point, energy_inside}` per detection; `point` in original-image pixels (FR-301/304); default on for detection
- [ ] T122 [US1] `app/services/config.py`: `HARNESS_GROUNDING_EXPLAINER` (`drise|gradcam|none`), `HARNESS_DRISE_MASKS`, `HARNESS_DRISE_MASK_RES`, `HARNESS_DRISE_SEED`; validation + defaults (FR-306/312)
- [ ] T123 [US1] No-egress: extractor invokes only `model.net.predict` on in-memory masked copies — no new I/O/network (FR-310); assert in the sandbox probe

## Phase 3 — Canonicalization fix (US2, the F6 correctness guard)

- [ ] T130 [US2] `engine/metrics/__init__.py::canonicalize()`: remap each `attribution` entry `label` via `label_map` (non-dict passes through), rebuilding `Prediction` with the attribution channel preserved (FR-305)
- [ ] T131 [US2] `engine/tiers/tier3_ops.py::run_tier3`: canonicalize the attributions via **`dataset.manifest.get("label_map")`** — the benchmark dataset already resolved at `tier3_ops.py:61`, mirroring `tier1_capability.py:55` — before `_grounding_evidence` scores them (today it uses raw `job.predictions`). **NO `orchestrator.py` change and NOT the Golden Set's `label_map`** — Tier 3 scores the registry stand-in benchmark, so the Golden Set map would map the wrong vocabulary (FR-305)

## Phase 4 — Timing, budget, Grad-CAM, provenance (US3/US4/US5)

- [ ] T140 [US4] Timing separation: clean detection pass is the sole `latency_ms_per_image`/`throughput`/`edge_deployable` source; explain time reported separately and excluded from the resource profile (FR-308)
- [ ] T141 [US4] Bounded explain: stop after `grounding_min_samples` targets; `log()` the cap (images explained / targets reached) — no silent truncation (FR-309). NOTE (per @claude review): "images explained" is a **pre-evaluation** heuristic on raw detections seen, while `evaluate_grounding`'s `min_samples` counts `n` **after** class-matching against canonicalized GT — the cap-reached log MUST NOT conflate the two; if canonicalization drops unmapped/unmatched attributions the run can still legitimately return `insufficient_samples` rather than `measured`
- [ ] T142 [US3] `engine/metrics/grounding_gradcam.py`: class-discriminative CAM over the detection head → same `{label, point, energy_inside}` envelope; clear infra failure on unsupported internals (FR-307)
- [ ] T143 [US5] `engine/cards/generator.py` + `templates/model_card.md.j2` + tier-result metrics: surface extractor (`drise`/`gradcam`), evaluator version, sample_count, resolvable `evidence_ref`/`evidence_digest` (FR-311)
- [ ] T144 [US5] (frontend, small) surface the grounding method on the model-detail Tier-3 row — `frontend/src/pages/ModelDetail.tsx`

## Phase 5 — Validation (all stories)

- [ ] T150 Full backend suite + constitution gates green; no Tier-1/2/3 regression; stub grounding path unchanged (FR-314)
- [ ] T151 Live: real `yolov8n.pt` produces a measured grounding score on a real (or synthetic-attend) fixture inside the sandbox; attribution + evidence digest reproducible (SC-004); recorded in `specs/004-real-model-grounding/validation.md`
- [ ] T152 [HW/data] Note the FR-315 dependency: a live end-to-end operational_safety **pass** needs a real road-scene golden set where the detector clears Tier 1/2 — recorded as a follow-up, not a code deliverable
- [ ] T153 Dual-bot review loop (@claude + @codex) → merge when clean
