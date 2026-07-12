# Implementation Plan: Real-Model Visual Grounding for Tier 3

**Branch**: `004-real-model-grounding` | **Date**: 2026-07-12 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/004-real-model-grounding/spec.md`

## Summary

Give the real PyTorch/YOLO **detection** adapter a way to produce genuine,
reproducible per-detection attribution evidence so the existing Tier-3 pointing-game /
energy-inside evaluators can MEASURE a real model against the ratified
`grounding_score ≥ 0.30` gate. The extractor is **D-RISE** (black-box saliency via
seeded masks) primary, **Grad-CAM** selectable; both emit `{label, point, energy_inside}`
into the existing `Prediction.attribution` channel. Two correctness/quality guards ride
along: attribution labels must be **canonicalized** (F6) before scoring, and the explain
phase must be **untimed** so the resource profile stays honest. No engine re-architecture,
no threshold change, no new evidence store — this slots into the 002 US5 grounding seam.

## Technical Context

**Language/Version**: Python 3.11 (backend/engine). No frontend change beyond surfacing the
grounding method (US5, small).

**Primary Dependencies**: Ultralytics YOLO + torch + numpy (sandbox `[ml]` extra) for the
saliency extractors; the existing `GroundingEvidence` contract, evaluators, and
content-addressed evidence store from 002 US5. `pycocotools` not required (grounding is
box/point math, not masks).

**Storage**: No schema change. Grounding evidence reuses the existing content-addressed
store (`results/evidence/<digest>.json`); the method/version travel on the tier result
metrics already carried by `GroundingEvidence.to_dict()`.

**Testing**: pytest (unit/integration), test-first (FR-313). ml-dependent paths (real
D-RISE/Grad-CAM saliency on a real checkpoint) validated live on the sandbox image; CI
installs `[dev]` only and exercises the math on synthetic fixtures.

**Target Platform**: Linux server; the no-egress `--network none` Docker sandbox runs the
untrusted model AND the extractor (which only invokes the loaded model on masked copies).

**Performance Goals**: POC-scale; D-RISE bounded to `grounding_min_samples` targets at a
default `N≈256` masks; explain time excluded from the resource profile.

**Constraints**: No-egress; deterministic/reproducible evidence (SC-004); grounding
measured-or-unavailable, never proxied (Forbidden substitutions); fail-closed unchanged.

**Scale/Scope**: One adapter capability (detection attribution) + a correctness fix
(canonicalization) + timing/provenance hygiene. Detection-only; classification/segmentation
grounding stays `unsupported_model_class`.

## Constitution Check

- **I Human-in-the-loop** — unchanged: an `unavailable` or sub-`0.30` grounding still
  routes to `pending_adjudication`; this feature only makes a *measured* pass *possible*,
  never automatic below the gate (FR-314).
- **II Licensing-clean** — no data committed; the extractor embeds no raw image pixels in
  evidence (points + energy scalars + method, same as existing grounding evidence).
- **III Benchmark-per-class** — Tier-3 grounding already exists; this supplies the missing
  *evidence producer* for the detection class, not a new metric.
- **IV No-egress / append-only** — the extractor runs the local model on in-memory masked
  copies inside `--network none`; evidence stays append-only + content-addressed (FR-310).
- **V Verify-first** — method + evaluator_version + sample_count + resolvable evidence_ref
  travel with every measured result; determinism makes it reproducible (FR-311/302).
- **VI Test-first** — saliency/math/canonicalization/timing tests written and observed
  failing before implementation (FR-313).

No violation; no complexity deviation requested.

## Architecture

### Extractor path (new) — Tier-3-only via an `explain` seam
`engine/metrics/grounding_drise.py` (and `grounding_gradcam.py`) implement a
`saliency(model, image, detection) -> SaliencyMap` producing, per emitted detection, the
peak point and the energy-inside-box fraction. The PyTorch adapter's `_predict_det` gains an
**explain** step that appends `{label, point, energy_inside}` to `Prediction.attribution`.
D-RISE only calls the existing `model.net.predict` on masked image copies (black-box);
Grad-CAM binds a hook on the detection head's last conv.

**Explain seam (R8, review findings #1 + follow-up):** the explain step must run **only in
Tier 3**, never Tier 1/2, because `run_inference` is tier-agnostic (one call in all three tiers
over one shared `predict()`) and attribution is consumed only by Tier 3. An
`explain: bool = False` parameter is threaded through `run_inference` → **the full execution
path**, not just the tier call-sites. That path has three legs the seam MUST cover
(second-round review): `run_inference` (`runner.py:140`) either (a) serializes a `spec` dict to
**`engine/sandbox/job.py::run(spec)`** (subprocess/docker) — where `adapter.predict()` actually
runs (`job.py:107`) and where `predict_s`/`latency_ms_per_image` are built (`job.py:118-123`) —
or (b) delegates over HTTP via **`app/services/runner_client.py::run_remote()`** (T073, when
`HARNESS_RUNNER_URL` is set), which today shares the same 4-arg signature and MUST forward
`explain`. Tier 1 (`:39`) and Tier 2 (`:82`) use the default (no attribution, no cost), Tier 3
(`:62`) passes `explain=True`. The global `HARNESS_GROUNDING_EXPLAINER` selects *which*
extractor Tier 3 uses; it does not by itself trigger attribution.

### Timing-separation path (FR-308, R3 — concrete split + mechanism)
`latency_ms_per_image`/`throughput`/`edge_deployable` stay sourced from the **clean** forward.
Today `job.py` times the whole `adapter.predict()` as one span (`job.py:105-110`) and builds
`predict_s`/`latency_ms_per_image` from it (`job.py:118-123`). **Pinned mechanism (second-round
review):** the split is achieved with a **separate, separately-timed `explain()` adapter step**,
not by changing `predict()`'s return type. When `spec["explain"]` is set, `job.py` runs the
timed clean `predict()` (→ `predict_s`, unchanged) **then** a separately-timed
`adapter.explain(model, images, preds)` (→ `explain_s`) that attaches attribution to the
predictions. `run_tier3` derives the resource profile from `predict_s` **only**; `explain_s`
never enters it. The `InferenceAdapter` protocol (`base.py`) therefore gains an optional
`explain()` (default: return `preds` unchanged — no-op for ONNX; the stub emits its synthetic
attribution here; the pytorch adapter runs D-RISE/Grad-CAM here). This is a localized change to
the `run_inference`/`job.py`/`runner_client.py`/`InferenceAdapter` contracts (**not**
`orchestrator.py`, not a transaction change); for `explain=False` the clean-pass timing is
byte-for-byte as today. (Corrects the earlier "separately and untimed" phrasing, which named no
seam — review finding #2 and its follow-up.)

### Canonicalization path (FR-305, the F6 fix)
`metrics.canonicalize()` is extended to remap the `attribution` channel's labels via the
`label_map` (mirroring the `labels`/`masks` remap). `tier3_ops.run_tier3` — whose
`_grounding_evidence` today builds attributions from **raw** `job.predictions` — canonicalizes
the attributions by **mirroring Tier 1's two-step sequence** (`tier1_capability.py:53-55`):
`[Prediction.from_dict(p) for p in job.predictions]` **then**
`canonicalize(preds, dataset.manifest.get("label_map") or {})` on the dataset it already
resolves at `tier3_ops.py:61`, so a COCO-vocabulary detector class-matches canonical GT. The
`from_dict` step is required — `canonicalize()` takes `list[Prediction]`, `job.predictions` is
`list[dict]` (review finding #4). This is the **registry stand-in benchmark** dataset (the same one
Tier 1 scores), **not** the Tier-2 Golden Set — so `run_tier3` needs no new argument and **no
`orchestrator.py` change**; using `golden.label_map` here would map against a different
dataset's vocabulary and reintroduce the false-fail. The stub path (identity/absent
`label_map`, GT-space labels) is unaffected.

### Evaluation + gate path (unchanged)
`evaluate_grounding` (pointing_game / energy_inside_region), `min_samples`, the ratified
`0.30` threshold, and the fail-closed `unavailable → adjudication` routing are all reused
verbatim. A measured score flows through `check_threshold` exactly as the stub's does.

### Evidence + provenance path (FR-311, unchanged mechanism)
The raw attributions are persisted by the orchestrator's existing
`_write_grounding_artifact` → `_write_content_addressed`; the method/version/sample_count
already ride on `GroundingEvidence.to_dict()`. US5 adds surfacing the method on the Model
Card grounding row.

## Project Structure

### Documentation (this feature)
```
specs/004-real-model-grounding/
  scoping.md       # pre-spec analysis (already written)
  spec.md          # US1–US5
  plan.md          # this file
  research.md      # R1–R7 (D-RISE, Grad-CAM, timing, canonicalization, determinism, budget)
  data-model.md    # attribution provenance; no persisted schema change
  contracts/
    grounding-attribution.md   # the attribution producer contract + determinism + timing
  quickstart.md    # run a real detector through Tier 3 with grounding on
  checklists/requirements.md
  tasks.md         # Phase 0–5 (test-first)
```

### Source Code (touched)
```
backend/engine/metrics/grounding_drise.py      # NEW: seeded-mask saliency → point + energy (FR-301/302/303)
backend/engine/metrics/grounding_gradcam.py    # NEW: class-discriminative CAM extractor (FR-307)
backend/engine/metrics/grounding.py            # (unchanged evaluator; may gain an energy-map helper)
backend/engine/sandbox/runner.py               # run_inference gains explain: bool = False; forward to BOTH legs
                                               #   (spec dict → job.py, and run_remote HTTP body) (FR-306a/308)
backend/engine/sandbox/job.py                  # run(spec): read spec["explain"]; after timed clean predict(),
                                               #   run separately-timed adapter.explain() → timing predict_s/explain_s (FR-306a/308)
backend/app/services/runner_client.py          # run_remote (CLIENT) gains explain + sends it in the HTTP body (T073) (FR-306a)
backend/runner/main.py                         # runner service (SERVER): RunRequest.explain: bool = False +
                                               #   POST /run forwards it to run_inference — else it silently no-ops under
                                               #   HARNESS_RUNNER_URL (Pydantic drops the unknown field) (FR-306a)
backend/engine/adapters/pytorch_adapter.py     # NEW adapter.explain(): run D-RISE/Grad-CAM, attach attribution (FR-301)
backend/engine/adapters/stub_adapter.py        # move synthetic attribution from predict() into explain() (Tier-3-only now)
backend/engine/tiers/tier1_capability.py       # pass explain=False (default — no change in effect) (FR-306a)
backend/engine/tiers/tier2_stress.py           # pass explain=False (default — no change in effect) (FR-306a)
backend/engine/adapters/base.py                # InferenceAdapter is a Protocol → explain() is OPTIONAL; job.py guards with
                                               #   getattr(adapter, "explain", None). Update Prediction.attribution docstring (FR-303, finding #6)
backend/engine/metrics/__init__.py             # canonicalize() remaps attribution labels (FR-305)
backend/engine/tiers/tier3_ops.py              # pass explain=True; from_dict → canonicalize attributions via
                                               #   dataset.manifest.label_map (mirrors tier1:53-55); latency from
                                               #   clean predict_s only (FR-305/306a/308/309)
                                               #   NOTE: no orchestrator.py change — Tier 3 uses the benchmark
                                               #   dataset it already resolves, not the Golden Set
backend/app/services/config.py                 # HARNESS_GROUNDING_EXPLAINER / DRISE_* config (FR-312)
backend/engine/cards/generator.py + template   # surface the grounding method/provenance (FR-311)
backend/tests/unit/test_grounding_drise.py     # NEW (FR-313)
backend/tests/unit/test_grounding_canon.py     # NEW: attribution canonicalization guard (FR-313)
backend/tests/integration/test_tier3_real_grounding.py  # NEW: measured grounding + timing exclusion (FR-313)
backend/tests/integration/test_sandbox_runtime.py       # live real-checkpoint grounding probe
```

**Structure Decision**: Single web-service repo; grounding extraction slots into the
existing Tier-3 / adapter seams — no new service, no schema, no new evidence store.

## Delivery Phases

- **Phase 0** — plan/research/data-model/contract (this set); settle method, timing model,
  determinism seeding, and the canonicalization fix.
- **Phase 1** — tests first (saliency determinism + math; pointing-game hit/miss fixture;
  canonicalization guard; timing-exclusion assertion), observed failing.
- **Phase 2** — D-RISE extractor + `adapter.explain()` step + `run_inference`/`job.py`/
  `runner_client` explain seam (Tier-3-only, timing split) + config surface.
- **Phase 3** — the F6 canonicalization fix: `canonicalize()` attribution remap + thread
  `label_map` into Tier 3 + evaluate canonicalized attributions.
- **Phase 4** — timing separation (explain untimed) + bounded/logged image cap + Grad-CAM
  alternative + Model Card method provenance.
- **Phase 5** — validation (full suite + gates green, no regression; live real-checkpoint
  grounding on the sandbox); dual-bot review → merge. Live end-to-end operational_safety
  pass is gated on a real golden set (FR-315) — recorded as an [HW] follow-up.

## Complexity Tracking

No constitution deviation. The genuinely new concept is the **saliency extractor** (D-RISE
seeded masks → peak/energy); most else reuses existing seams — the `attribution` channel and
`GroundingEvidence` contract already exist (002 US5), canonicalization already exists for
other channels (extended here), and the gate/routing/evidence store are untouched.

**One localized contract change (post-review, blast radius pinned across three review rounds):**
the explain seam touches these backend files, none of them the orchestrator or a transaction:
`run_inference` (`runner.py`) gains `explain: bool = False` and forwards it down **both** legs;
`job.py::run(spec)` reads `spec["explain"]` and runs a separately-timed `adapter.explain()`
(invoked via `getattr(adapter, "explain", None)`) after the clean `predict()`, building
`predict_s`/`explain_s`; the T073 HTTP leg carries it on **both** sides —
`runner_client.run_remote()` (client) sends it and `backend/runner/main.py`
(`RunRequest`/`POST /run`, server) accepts + forwards it, else it silently no-ops under
`HARNESS_RUNNER_URL`; `InferenceAdapter` (a `Protocol`) gains an **optional** `explain()`
(pytorch + stub implement it, ONNX unchanged via the `getattr` guard); and the stub's synthetic
attribution moves from `predict()` into `explain()` (Tier-3-only — grounding *verdict* unchanged,
FR-314). This is required to (a) confine the expensive extractor to Tier 3 — tier-agnostic today
(FR-306a / review #1) — and (b) keep the resource profile honest (FR-308 / review #2).
`explain=False` preserves today's behavior byte-for-byte on every leg. Correctness risks —
foreign-vocabulary false-fail (FR-305), explain-in-every-tier cost (FR-306a), and the silent
remote-runner no-op — are each closed by a dedicated Phase-1 test (T111, T116, T117).
