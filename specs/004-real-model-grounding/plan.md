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

### Extractor path (new)
`engine/metrics/grounding_drise.py` (and `grounding_gradcam.py`) implement a
`saliency(model, image, detection) -> SaliencyMap` producing, per emitted detection, the
peak point and the energy-inside-box fraction. The PyTorch adapter's `_predict_det` gains
an opt-in **explain** step (default on for detection) that, after the normal detections,
runs the configured extractor and appends `{label, point, energy_inside}` to
`Prediction.attribution`. D-RISE only calls the existing `model.net.predict` on masked
image copies (black-box); Grad-CAM binds a hook on the detection head's last conv.

### Timing-separation path (FR-308)
The clean detection pass (already the latency source for Tier 1/2/3) stays timed and
untouched; the explain step runs in a **separate, untimed** phase. Concretely: the adapter
records clean-inference timing exactly as today and reports explain time (if any) under a
distinct key that Tier 3 does **not** fold into `latency_ms_per_image`/`edge_profile`.
(Decision R3: two-phase — clean timed + explain untimed — over single-job split timing.)

### Canonicalization path (FR-305, the F6 fix)
`metrics.canonicalize()` is extended to remap the `attribution` channel's labels via the
`label_map` (mirroring the `labels`/`masks` remap). `tier3_ops.run_tier3` — whose
`_grounding_evidence` today builds attributions from **raw** `job.predictions` — canonicalizes
the attributions using **the benchmark dataset's own `manifest.label_map`**
(`dataset.manifest.get("label_map")`, the exact seam Tier 1 uses at `tier1_capability.py:55`),
on the dataset it already resolves at `tier3_ops.py:61`, so a COCO-vocabulary detector
class-matches canonical GT. This is the **registry stand-in benchmark** dataset (the same one
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
backend/engine/adapters/pytorch_adapter.py     # _predict_det explain step; two-phase timing (FR-301/308)
backend/engine/adapters/base.py                # (attribution channel already exists — no change)
backend/engine/metrics/__init__.py             # canonicalize() remaps attribution labels (FR-305)
backend/engine/tiers/tier3_ops.py              # canonicalize attributions via dataset.manifest.label_map
                                               #   (mirrors tier1:55); exclude explain time from profile (FR-305/308/309)
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
- **Phase 2** — D-RISE extractor + `_predict_det` explain step (default on) + config surface.
- **Phase 3** — the F6 canonicalization fix: `canonicalize()` attribution remap + thread
  `label_map` into Tier 3 + evaluate canonicalized attributions.
- **Phase 4** — timing separation (explain untimed) + bounded/logged image cap + Grad-CAM
  alternative + Model Card method provenance.
- **Phase 5** — validation (full suite + gates green, no regression; live real-checkpoint
  grounding on the sandbox); dual-bot review → merge. Live end-to-end operational_safety
  pass is gated on a real golden set (FR-315) — recorded as an [HW] follow-up.

## Complexity Tracking

No constitution deviation. The genuinely new concept is the **saliency extractor** (D-RISE
seeded masks → peak/energy); everything else reuses existing seams — the `attribution`
channel and `GroundingEvidence` contract already exist (002 US5), canonicalization already
exists for other channels (extended here), and the gate/routing/evidence store are
untouched. The one correctness risk (foreign-vocabulary false-fail) is closed by FR-305 and
guarded by a dedicated test.
