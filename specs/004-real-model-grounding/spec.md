# Feature Specification: Real-Model Visual Grounding for Tier 3

**Feature Branch**: `004-real-model-grounding`

**Created**: 2026-07-12

**Status**: Draft (for review)

**Input**: User request — "find me a CV model that would likely pass operational_safety" → investigation showed no *real* model can pass Tier 3 today because the real detection adapter emits no attribution evidence and the grounding evaluator (correctly) refuses proxies. This feature builds the missing evidence path. Pre-spec analysis in [scoping.md](./scoping.md).

**Constitution**: governed by v1.0.0 (`.specify/memory/constitution.md`). Principle I (Human-in-the-Loop) and the metric-evidence rule "grounding MUST be measured from reproducible localization evidence, never approximated" (002 `metric-evidence.md §Forbidden substitutions`) are the load-bearing constraints here.

## Purpose and scope

Tier 3 (`operational_safety`) gates a model on **measured visual grounding** —
`grounding_score ≥ 0.30` (ratified) via the pointing-game / energy-inside
evaluators. Today the gate is unreachable for any real model:

| Blocker | Where | Consequence |
|---|---|---|
| Only detection is localizable | `tier3_ops.LOCALIZATION_CLASSES = {detection}` | classification/segmentation → `unavailable(unsupported_model_class)` (correct, keep) |
| Real detector emits no attribution | `PyTorchAdapter._predict_det` returns `boxes/scores/labels` only | every real `.pt` → `missing_attribution → unavailable → adjudication` |

Only the **stub** adapter produces attribution (a synthetic point on the GT box),
which is why `healthy-detector` passes and no real model does. This feature gives
the real PyTorch/YOLO **detection** adapter a way to produce **genuine,
reproducible per-detection attribution evidence**, so a capable real detector can
be MEASURED by the existing evaluators and clear the ratified gate honestly — with
no change to the threshold, the fail-closed routing, or the human-adjudication gate.

## Clarifications

### Session 2026-07-12

- Q: Which attribution method? → A: **D-RISE primary** (black-box saliency via seeded
  random masks — respects the adapter boundary, robust across Ultralytics versions,
  per-detection and class-discriminative, deterministic) **plus Grad-CAM** as a
  selectable faster alternative (US3).
- Q: On by default or opt-in? → A: **On by default for detection**, selectable/disable
  via `HARNESS_GROUNDING_EXPLAINER` (`drise|gradcam|none`), so a capable real model
  can auto-pass Tier 3 without extra operator config.
- Q: What evidence per detection? → A: **Both** `point` (saliency peak → pointing_game)
  **and** `energy_inside` (energy fraction inside the box → energy_inside_region), so
  both approved methods are fed from one saliency map.
- Q: Does grounding extend to classification/segmentation? → A: **No.** They remain
  `unavailable(unsupported_model_class)` (no localization target) — fail-closed
  unchanged. Grounding is detection-only for this feature.
- Q: Is a live end-to-end pass in scope? → A: The **measurement path** is in scope; a
  real model only *reaches* Tier 3 after clearing Tier 1/2, so a live pass also needs a
  real golden set where the detector clears capability (a separate [HW] data step,
  US1 acceptance #5).

## User Scenarios & Testing *(mandatory)*

### User Story 1 — A real detector produces measurable grounding (Priority: P1) — ⬜ TODO

A submitter uploads a real Ultralytics YOLO **detection** checkpoint. During Tier 3
the adapter computes a real per-detection saliency map and emits attribution points,
so the pointing-game evaluator returns a **measured** `grounding_score` instead of
`unavailable(missing_attribution)` — and a well-grounded detector clears `≥ 0.30`.

**Why this priority**: This is the whole feature — without attribution evidence no
real model can ever pass Tier 3; P1.

**Independent Test**: For a detection model whose saliency lands inside the correct
class's boxes, Tier 3 returns `grounding.status == "measured"` with `sample_count ≥
grounding_min_samples` and a `grounding_score` matching a reference pointing-game
computation on the emitted attributions; for a model whose saliency lands outside,
the score is correspondingly low. The evidence is content-addressed and reproduces
byte-identically on re-run.

**Acceptance Scenarios**:

1. **Given** a real detection checkpoint and the D-RISE explainer, **When** Tier 3
   runs, **Then** each emitted detection carries `{label, point:[x,y], energy_inside}`
   with `point` in original-image pixel coordinates, and grounding is `measured`.
2. **Given** identical inputs (same weights, same images, same seed), **When** the run
   is repeated, **Then** the saliency maps, attribution points, and the evidence
   digest are **identical** (SC-004) — determinism from a seeded mask stream.
3. **Given** a detector that attends to the correct regions, **When** grounding is
   scored, **Then** `grounding_score ≥ 0.30` and Tier 3 can auto-pass (subject to the
   existing gate + human-adjudication rules); a detector that attends elsewhere scores
   below the floor and routes to adjudication.
4. **Given** the explainer is set to `none`, **When** Tier 3 runs, **Then** attribution
   is empty and grounding is `unavailable(missing_attribution)` — the prior fail-closed
   behavior, unchanged.
5. **Given** a real detector that has NOT cleared Tier 1/2 on the golden set, **When**
   evaluated, **Then** it is rejected/adjudicated before Tier 3 (this feature does not
   change T1/T2 gating); a live end-to-end pass additionally requires a golden set
   where the detector clears capability (data step, [HW]).

---

### User Story 2 — Foreign-vocabulary attribution is canonicalized (Priority: P1) — ⬜ TODO

A COCO-trained detector emits attribution on `person`/`car`; the Tier-3 benchmark
dataset's ground truth is `pedestrian`/`vehicle`. The pointing-game matches attribution
label against GT label, so attribution labels MUST be canonicalized through **the
Tier-3-resolved benchmark dataset's own `manifest.label_map`** (F6) **before** grounding
is evaluated — exactly as Tier 1 canonicalizes capability predictions
(`tier1_capability.py:55`) — otherwise a correctly-grounded real model scores ≈ 0 (a
false fail).

> **Seam note (review):** Tier 3 scores against `resolve(get_benchmark(model_class).dataset)`
> — the **registry stand-in benchmark** (the same dataset Tier 1 uses), **not** the Tier-2
> Golden Set. The correct `label_map` is that benchmark dataset's `manifest.json` one; using
> the Golden Set's `label_map` would map to a different dataset's vocabulary and silently
> reintroduce the false-fail. `run_tier3` already has `dataset` in scope, so no orchestrator
> change is needed.

**Why this priority**: Without it, US1 silently produces false fails for every
foreign-vocabulary (i.e. every real COCO) detector; P1, and a correctness bug.

**Independent Test**: A detector emitting attribution on `person`, scored against a
Tier-3 benchmark dataset whose GT class is `pedestrian` and whose `manifest.label_map`
is `{person: pedestrian}`, produces a pointing-game **hit** for a point inside the
pedestrian box; without canonicalization the same input produces a miss.

**Acceptance Scenarios**:

1. **Given** the benchmark dataset's `manifest.label_map` renames `person → pedestrian`,
   **When** grounding is evaluated, **Then** an attribution
   `{label: person, point: <inside pedestrian box>}` is canonicalized to `pedestrian` and
   counts as a **hit**.
2. **Given** the stub grounding path (attribution already in the GT label space, identity
   `label_map`), **When** grounding is evaluated, **Then** behavior is **unchanged**
   (no regression to existing Tier-3 tests).

---

### User Story 3 — Grad-CAM as a selectable extractor (Priority: P2) — ⬜ TODO

An operator selects `HARNESS_GROUNDING_EXPLAINER=gradcam` for a faster, gradient-based
class-discriminative saliency (one backward pass per detection over the detection head)
producing the same `{label, point, energy_inside}` evidence shape.

**Why this priority**: D-RISE (US1) makes real grounding possible; Grad-CAM is a
speed/quality alternative, not required for the first pass. P2.

**Independent Test**: With the gradcam explainer, a detection model emits the same
attribution envelope as D-RISE, and the grounding evaluator scores it identically in
shape; determinism holds (no mask RNG — deterministic given fixed weights/inputs).

**Acceptance Scenarios**:

1. **Given** `HARNESS_GROUNDING_EXPLAINER=gradcam`, **When** Tier 3 runs, **Then**
   attribution is produced from a class-discriminative CAM over the detection head and
   is `measured`.
2. **Given** an Ultralytics version whose internals the CAM hook cannot bind, **When**
   the gradcam extractor initializes, **Then** it fails to a clear infra reason (or
   documented fallback), never a silent wrong-region attribution.

---

### User Story 4 — Grounding cost does not corrupt the resource profile (Priority: P2) — ⬜ TODO

Attribution extraction is expensive (D-RISE = N forward passes per image). It MUST NOT
inflate the Tier-3 resource profile (`latency_ms_per_image`, `throughput`,
`edge_deployable`), which is measured from the clean inference pass; and it MUST be
bounded so a large golden set does not run unboundedly.

**Why this priority**: A correct grounding score with a corrupted latency metric would
mislead the edge-deployability signal; P2 (informational metric, not a gate).

**Independent Test**: `latency_ms_per_image` and `edge_profile` for a run **with** the
explainer equal those for the clean pass (within tolerance) — the explain phase is
excluded from timing; and the run explains only enough images to reach
`grounding_min_samples`, logging the cap.

**Acceptance Scenarios**:

1. **Given** the explainer is on, **When** Tier 3 records timing, **Then**
   `latency_ms_per_image`/`throughput`/`edge_deployable` reflect the **clean** inference
   only, not the explain phase (clean-vs-explain timing split).
2. **Given** a golden set larger than needed, **When** grounding runs, **Then** it
   explains images only until `grounding_min_samples` targets are reached and **logs**
   the cap (no silent truncation).
3. **Given** the explainer is `drise`, **When** Tier 1 and Tier 2 run inference, **Then**
   no attribution is produced and no explain cost is incurred (`explain=False` by default);
   attribution is requested only by Tier 3 (`explain=True`) — review finding #1.

---

### User Story 5 — Grounding method provenance is auditable (Priority: P2) — ⬜ TODO

A measured Tier-3 pass records **which** method produced the evidence (`drise`/`gradcam`),
its evaluator version, and the resolvable content-addressed evidence reference, and the
Model Card surfaces it, so an auditor can reproduce and trust the grounding.

**Why this priority**: Verify-first (Constitution V) — a measured pass must be
attributable and reproducible; P2.

**Acceptance Scenarios**:

1. **Given** a measured grounding result, **When** it is persisted, **Then** the tier
   result + Model Card carry the method, evaluator version, sample count, and
   `evidence_ref`/`evidence_digest` (the existing content-addressed store).
2. **Given** two runs with the same inputs, **When** their evidence digests are compared,
   **Then** they are identical (SC-004).

---

## Requirements *(mandatory)*

### New — Real-model grounding (US1–US5)

- **FR-301** (US1) The PyTorch **detection** adapter MUST produce per-detection
  attribution evidence from a **real saliency method**, emitting one
  `{ "label": str, "point": [x, y], "energy_inside": float }` per emitted detection.
  The evidence MUST NOT be approximated from confidence, entropy, parameter count,
  latency, or any adapter scalar (002 `metric-evidence.md §Forbidden substitutions`).
- **FR-302** (US1) The D-RISE extractor MUST be **deterministic**: its random-mask
  stream is seeded from `weights_digest + image_id` so identical inputs yield identical
  saliency, identical attribution, and an identical evidence digest (SC-004).
- **FR-303** (US1) The adapter MUST emit **both** `point` (the saliency-map peak, in
  original-image pixel coordinates — the pointing-game input) **and** `energy_inside`
  (the fraction of saliency energy inside the detection box, in `[0,1]` — the
  energy-inside-region input) per detection, so **either** approved method can score the
  evidence. **Clarification (per review):** `evaluate_grounding` selects the
  **first-applicable** method from `HARNESS_GROUNDING_METHODS` (default
  `("pointing_game", "energy_inside_region")`), so once every entry carries a `point`,
  `pointing_game` always applies and scores; `energy_inside` is then **retained,
  reproducible evidence** that `energy_inside_region` scores only when it is configured
  first or when points are absent. FR-303 does **not** claim both methods score
  simultaneously — it guarantees both are *feedable* from one saliency map.
- **FR-304** (US1) An attribution `point` MUST be in the **original-image pixel frame**
  (the same coordinate space as the XYXY boxes the grounding evaluator compares against).
- **FR-305** (US2) Attribution labels MUST be **canonicalized through the Tier-3-resolved
  benchmark dataset's own `manifest.label_map` before grounding is evaluated**:
  `metrics.canonicalize()` MUST remap the `attribution` channel's labels (as it already
  does for `labels`/`masks`), and `tier3_ops.run_tier3` MUST canonicalize the attributions
  using `dataset.manifest.get("label_map")` — the **same benchmark dataset it already
  resolves** at `tier3_ops.py:61` and the **same seam Tier 1 uses** (`tier1_capability.py:55`)
  — before `_grounding_evidence` scores them (today Tier 3 evaluates raw `job.predictions`
  with no canonicalization). The Tier-3 fix MUST mirror Tier 1's **exact sequence**
  (`tier1_capability.py:53-55`): `preds = [Prediction.from_dict(p) for p in job.predictions]`
  **then** `canonicalize(preds, dataset.manifest.get("label_map") or {})` — because
  `metrics.canonicalize()` operates on `list[Prediction]`, while `job.predictions` is raw
  `list[dict]`; calling `canonicalize()` on the dicts directly would raise `AttributeError`
  (review finding #4). The attribution channel MUST survive `from_dict`/`to_dict`
  (it already does, `base.py:65,79`). The `label_map` MUST come from that benchmark dataset's
  manifest, **not** the Tier-2 Golden Set (which scores a different dataset); no
  `orchestrator.py` change is required. Otherwise a foreign-vocabulary detector class-matches
  zero targets and false-fails (F6).
- **FR-306** (US1) The attribution extractor MUST run **on by default for detection**,
  selectable/disable via `HARNESS_GROUNDING_EXPLAINER` (`drise` | `gradcam` | `none`);
  `none` restores the prior `missing_attribution` behavior.
- **FR-306a** (US1/US4) The extractor MUST run **only in Tier 3**, never in Tier 1 or
  Tier 2 (review finding #1). Today `run_inference` is tier-agnostic — the identical call
  is made in all three tiers (`tier1_capability.py:39`, `tier2_stress.py:82`,
  `tier3_ops.py:62`) over one shared adapter `predict()` — and attribution is consumed
  **only** by Tier 3's `_grounding_evidence`. Gating the explainer on the global
  `HARNESS_GROUNDING_EXPLAINER` alone would run D-RISE's ~`N` passes/image on every Tier-1
  inference and on every Tier-2 perturbation condition, discarding the output twice.
  Therefore an explicit **explain seam** MUST be threaded so only Tier 3 requests
  attribution: `run_inference(..., explain: bool = False)` (default off) forwarded down **the
  whole execution path**, which has two legs (second-round review): the serialized `spec` dict
  into `engine/sandbox/job.py::run(spec)` (subprocess/docker — where `adapter.predict()` runs,
  `job.py:107`) **and** the HTTP call to the dedicated runner service. The HTTP leg has a
  **client and a server**, both of which MUST carry `explain` (third-round review):
  `app/services/runner_client.py::run_remote()` sends it in the body, **and**
  `backend/runner/main.py` MUST accept it — `RunRequest` (`main.py:49-53`) gains
  `explain: bool = False` and the `POST /run` handler (`main.py:76-90`) forwards it to its local
  `run_inference(...)`. Otherwise Pydantic silently drops the unknown field and Tier-3
  attribution **silently no-ops whenever `HARNESS_RUNNER_URL` is configured** (the T073
  production profile — a silent empty-attribution failure, not a loud one). Tier 1/2 call with
  the default (`explain=False` → no attribution, no cost), Tier 3 with `explain=True`.
- **FR-307** (US3) A **Grad-CAM** extractor MUST be available as a selectable alternative
  (class-discriminative CAM over the detection head), producing the same
  `{label, point, energy_inside}` envelope; a binding failure on an unsupported
  Ultralytics internal MUST surface as a clear infra reason, never a silent wrong point.
- **FR-308** (US4) The explain phase MUST NOT inflate the Tier-3 resource profile:
  `latency_ms_per_image`, `throughput_images_per_s`, and `edge_deployable` MUST reflect
  the **clean** inference pass only; grounding-extraction time is measured/excluded
  separately. **Concrete seam + mechanism (review finding #2 + follow-up):** today `job.py`
  times the whole `adapter.predict()` as one span (`job.py:105-110`) and builds
  `predict_s`/`latency_ms_per_image` from it (`job.py:118-123`). The split MUST be done with a
  **separate, separately-timed `explain()` adapter step** (not by changing `predict()`'s return
  type): when `spec["explain"]` is set, `job.py` runs the timed clean `predict()`
  (→ `predict_s`, unchanged) **then** a separately-timed `adapter.explain(model, images, preds)`
  (→ `explain_s`) that attaches attribution. `run_tier3` MUST derive `latency_ms_per_image`/
  `throughput`/`edge_deployable` from the **clean** `predict_s` only. `InferenceAdapter` is a
  `typing.Protocol` (no default method bodies — `base.py:105`), so `explain()` is an **optional**
  member and `job.py` MUST invoke it via `getattr(adapter, "explain", None)` — calling it when
  present and `spec["explain"]`, skipping otherwise. Only the pytorch and stub adapters implement
  `explain()`; ONNX and any other adapter need **no** change (the `getattr` guard is the no-op).
  This touches the `run_inference`/`job.py`/`runner_client.py`/`backend/runner/main.py`/
  `InferenceAdapter` contracts (not `orchestrator.py`); for `explain=False` every leg is
  byte-for-byte as today.
- **FR-309** (US4) The extractor MUST be **bounded**: explain only enough images to reach
  `grounding_min_samples` target instances, and MUST `log()` the cap so coverage is
  honest (no silent truncation).
- **FR-310** (US1) No-egress: the extractor MUST run **only the already-loaded local
  model** on in-memory (masked) image copies — no network, no auto-download, no new
  filesystem reads beyond the dataset already mounted (Constitution IV).
- **FR-311** (US5) The Tier-3 result and Model Card MUST surface the grounding **method**,
  `evaluator_version`, `sample_count`, and the resolvable `evidence_ref`/`evidence_digest`
  (reusing the existing content-addressed evidence store), so a measured pass is
  auditable and reproducible.
- **FR-312** (US1/US3) Config surface: `HARNESS_GROUNDING_EXPLAINER`,
  `HARNESS_DRISE_MASKS` (N), `HARNESS_DRISE_MASK_RES`, `HARNESS_DRISE_SEED`; the existing
  `HARNESS_GROUNDING_METHODS` and `HARNESS_GROUNDING_MIN_SAMPLES` are reused unchanged.
- **FR-313** (US1–US4) Tests MUST be written first and observed failing (Constitution VI):
  saliency determinism; peak→point and energy-fraction math; a synthetic attend-right
  → pointing-game **hit** / attend-wrong → **miss** fixture; the FR-305 canonicalization
  guard (incl. the `from_dict → canonicalize` sequence); the **FR-306a Tier-1/2 non-invocation**
  assertion (no attribution/no explain cost when `explain=False`); and the FR-308
  clean-vs-explain timing-split assertion (Tier-3 `latency_ms_per_image` unchanged with the
  explainer on).
- **FR-316** (US1, informational — review finding #5) The two approved methods define
  `sample_count` differently: `_pointing_game` counts **GT target boxes**, while
  `_energy_inside_region` counts **attribution entries** (`grounding.py:114-116` vs
  `:130-133`), yet both gate on the same `grounding_min_samples`. When
  `energy_inside_region` is the scoring method, `insufficient_samples` is cleared on the
  volume of the model's own predictions, a weaker/differently-defined bar than target
  coverage. The default (`pointing_game` first) is unaffected; if `energy_inside_region` is
  ever configured as primary, the min-samples semantics MUST be documented (or the evaluator
  aligned to count targets). No behavior change is mandated for the default in this feature.

### Invariants (unchanged, must hold)

- **FR-314** Classification and segmentation grounding MUST remain
  `unavailable(unsupported_model_class)` (no localization target — fail-closed
  unchanged). The **stub** grounding *verdict/evidence* MUST NOT regress, the ratified
  `grounding_score ≥ 0.30` gate, the fail-closed routing, and all existing Tier-1/2/3 behavior
  MUST NOT regress; the full backend suite + constitution gates stay green. (Note: the stub's
  synthetic attribution moves from `predict()` into the new `explain()` step, so it is now
  produced only in Tier 3 with `explain=True` — the grounding result Tier 3 sees is identical;
  only the emission point moves, consistent with FR-306a.)
- **FR-315** (informational) A real model reaches Tier 3 only after clearing Tier 1
  (`coco_ap_50_95 ≥ 0.25`) and Tier 2. This feature ships the **measurement path**; a
  live end-to-end operational_safety pass additionally requires a real golden set where
  the detector clears capability — a separate data/[HW] step, not a code deliverable
  here.

## Delivery status

| Story | Priority | Status | Target |
|---|---|---|---|
| US1 real detector measurable grounding (D-RISE) | P1 | ⬜ To build | this feature |
| US2 attribution label canonicalization (F6 fix) | P1 | ⬜ To build | this feature |
| US3 Grad-CAM selectable extractor | P2 | ⬜ To build | this feature |
| US4 timing honesty + bounded explain | P2 | ⬜ To build | this feature |
| US5 method provenance + card | P2 | ⬜ To build | this feature |

## Out of scope

- Grounding for classification/segmentation (no localization target — remains
  `unsupported_model_class`).
- Changing the ratified `0.30` grounding threshold or the fail-closed routing.
- Robustness / drift / shortcut probes (already out of scope for the Tier-3 POC).
- Fetching/curating the real road-scene golden set that lets a real model *reach* Tier 3
  (data step; the measurement path is what this feature delivers — FR-315).
- ONNX detection attribution (the PyTorch/Ultralytics path is the reference).

## Assumptions

- Ultralytics + torch remain the reference detection loader (already in the sandbox image);
  D-RISE only calls the existing `.predict` path, so it is version-robust.
- POC scale — tens of images per golden set; D-RISE at a bounded `N` (default ~256 masks)
  on a nano detector runs in the sandbox in a couple of minutes on the reference GPU.
- CI installs `[dev]` (no ml extra); the D-RISE/Grad-CAM real paths are validated live on
  the sandbox image, as with detection (F9), classification (US3), and segmentation (US4).
- The existing content-addressed grounding-evidence store and the `GroundingEvidence`
  contract (002 US5) are reused unchanged for the new evidence.
