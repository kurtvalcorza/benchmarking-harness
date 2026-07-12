# Scoping: Real-Model Visual Grounding for Tier 3 (operational_safety)

**Status**: SCOPING — for review before a full Spec-Kit `spec.md`/`plan.md`.
**Feature (prospective)**: `004-real-model-grounding`
**Depends on**: 002 US5 (grounding evidence contract), 003 (CV adapters).

---

## 1. Problem

A real, downloadable CV model **cannot pass `operational_safety` today**, and the
reason is structural, not a threshold tune:

1. **Only detection is localizable.** `tier3_ops.LOCALIZATION_CLASSES = {detection}`.
   Classification and segmentation return `unavailable(unsupported_model_class)` →
   routed to adjudication, never an auto-pass. *(By design — keep it.)*
2. **The real detection adapter emits no attribution evidence.**
   `PyTorchAdapter._predict_det` returns `boxes/scores/labels` and nothing else, so
   `Prediction.attribution == []`. The grounding evaluator reads **only** that
   channel and — per `metric-evidence.md §Forbidden substitutions` — refuses to
   approximate grounding from confidence/entropy/params/latency. Result for every
   real `.pt`/`.onnx` detector: `missing_attribution → unavailable → adjudication`.

The **only** path that produces attribution today is the *stub* adapter (it keys a
synthetic point on the GT box with a configurable hit-rate). That is why
`healthy-detector` (`grounding: 0.82`) passes and no real model does.

**Goal of this feature:** give the real PyTorch/YOLO detection adapter a way to
produce *genuine, reproducible* per-detection attribution evidence, so a capable
real detector can be **MEASURED** by the existing pointing-game / energy-inside
evaluators and clear the ratified `grounding_score ≥ 0.30` gate honestly.

### Non-goals
- No change to the `0.30` ratified threshold or the fail-closed routing.
- No grounding for classification/segmentation (no localization target — keep
  `unsupported_model_class`).
- No robustness/drift/shortcut probes (already out of scope for Tier 3 POC).

---

## 2. What "measured" requires (the contract we must satisfy)

From `grounding.py` + `metric-evidence.md §GroundingEvidence`:

- `Prediction.attribution: list[{ "label": str, "point": [x, y] }]` (pointing game)
  **or** `{ "label": str, "energy_inside": float in [0,1] }` (energy method).
- `point` is in **original-image pixel coords** (same frame as the XYXY boxes —
  `_inside()` compares directly).
- `label` must be in the **dataset (canonical) label space**, because pointing-game
  matches `attr.label == gt.label`.
- `sample_count ≥ grounding_min_samples` (default **20** target instances).
- `score` finite in `[0,1]`; evidence persisted content-addressed (already handled
  by the orchestrator's `_write_content_addressed`).

---

## 3. Approach — attribution extractor

Three candidate methods; the adapter boundary (we only hold an Ultralytics `YOLO`
object and call `.predict`) drives the choice.

| Method | Class-discriminative? | Needs internal hooks? | Deterministic? | Cost |
|---|---|---|---|---|
| **EigenCAM** | ✗ (class-agnostic) | yes (last conv) | yes | cheap |
| **Grad-CAM / ++** | ✓ | yes (layer + gradients; Ultralytics predict runs no-grad) | yes | 1 backward / detection |
| **D-RISE** | ✓ (per-detection target vector) | **no — black box** | yes (seeded masks) | N forward / image |

### Recommendation: **D-RISE primary**, Grad-CAM as an optional faster follow-up.

D-RISE (Petsiuk 2021, *black-box explanation of object detectors*):
1. Generate `N` seeded low-res random masks, upsample + random-shift to image size.
2. Run the detector on each masked image (uses the **existing** `.predict` path —
   no version-fragile layer hooking).
3. For a target detection `d*` (box `b*`, class `c*`, score `s*`), weight each mask
   by the detection-vector similarity `IoU(b*, b) · cos(class-probs) · objectness`
   of the best-matching detection in the masked output.
4. Saliency `S = Σ wᵢ·Mᵢ`; **peak(S) → `point`**, **energy(S ∩ b*) → `energy_inside`**.

Why it fits *this* codebase:
- **Respects the adapter black-box boundary** → robust across Ultralytics releases
  (the classification/segmentation loaders already lean on this).
- **Per-detection & class-discriminative by construction** → real pointing-game
  semantics, not a proxy (satisfies Forbidden-substitutions).
- **Deterministic** when the mask RNG is seeded from `weights_digest + image_id`
  → content-addressed evidence stays reproducible across reruns (SC-004).
- **Emits both** `point` and `energy_inside`, feeding both approved methods for free.

Cost is bounded: masks are per-image and reused across all target detections in that
image, so cost ≈ `N × (#images needed to reach 20 targets)`. With `N≈256` and ~20
images that is a few thousand `yolov8n` forward passes — ~1–2 min on the RTX 5070 Ti,
and cappable (see §6).

---

## 4. Where it plugs in

- **`Prediction.attribution`** — already exists; **no envelope change**.
- **`_predict_det`** gains an opt-in `explain` path: after the normal detections,
  run the extractor and append one `{label, point, energy_inside}` per detection.
- **Timing separation (decision):** Tier 3 sources `latency_ms_per_image` from the
  clean predict pass. D-RISE must **not** inflate it. Recommended shape: keep the
  **clean, timed** inference pass as the latency source, and run the extractor as a
  **separate, untimed explain phase**. (Alternative: single job where the adapter
  reports clean-vs-explain timing split and Tier 3 uses only the clean split.)
- **Evidence & routing** downstream are unchanged — a measured score flows through
  `check_threshold` against the existing ratified `0.30`.

---

## 5. Correctness must-fix — attribution label canonicalization (F6)

**Found during scoping.** `canonicalize()` remaps `labels`, `label`, `class_scores`,
and `masks` — **but not `attribution`** — and `tier3_ops._grounding_evidence`
builds attributions from **raw** `job.predictions` with **no canonicalization at
all**. A real COCO detector emits attribution on `"person"`/`"car"`; the golden GT
is `"pedestrian"`/`"vehicle"`. Pointing-game would class-match **zero** targets →
`grounding ≈ 0` → **false fail**.

**Fix (in-scope):** canonicalize attribution labels in `run_tier3` using **the Tier-3
benchmark dataset's own `manifest.label_map`** (`dataset.manifest.get("label_map")`, the
seam Tier 1 uses at `tier1_capability.py:55`) before `evaluate_grounding`, and extend
`canonicalize()` to also remap the `attribution` channel. **Correction (per @claude review
of PR #18):** Tier 3 scores the registry stand-in benchmark
(`resolve(get_benchmark(model_class).dataset)`), **not** the Tier-2 Golden Set — so the map
must come from that benchmark dataset's manifest, not `golden.label_map`, and **no
`orchestrator.py` change** is needed. See spec.md FR-305 / research.md R4 for the authoritative
wording. *The stub path is unaffected* (it already keys on the GT
label; owned samples use an identity `label_map`).

---

## 6. Determinism, budget, config

- **Determinism:** seed the D-RISE mask stream from `weights_digest + image_id`
  (torch is already `manual_seed(1234)`); identical inputs → identical saliency →
  identical evidence bytes/digest.
- **Budget cap (no silent caps):** explain only the first `K` images that supply
  ≥ `grounding_min_samples` targets; `log()` the cap so coverage is honest.
- **Config surface (new env):** `HARNESS_GROUNDING_EXPLAINER` (`drise|gradcam|none`),
  `HARNESS_DRISE_MASKS` (N), `HARNESS_DRISE_MASK_RES`, `HARNESS_DRISE_SEED`.
  Reuse existing `HARNESS_GROUNDING_METHODS` / `HARNESS_GROUNDING_MIN_SAMPLES`.
  **Decision:** default the explainer **off** (opt-in) so no run silently pays the
  D-RISE latency, or **on for detection** to make real passes the default. TBD.
- **No-egress:** the extractor only runs the already-loaded local model on
  in-memory masked copies — no new I/O, no network. Runs inside the sandbox.

---

## 7. Test-first plan (Constitution VI / FR-209)

Written and observed failing before impl:
- **Unit** (`test_grounding_drise.py`): saliency determinism (same seed → same map);
  peak→point and energy-fraction math; a synthetic 2-box image where the model
  attends to the correct region → pointing-game **hit**, wrong region → **miss**.
- **Unit** (canonicalization): attribution `"person"` scores against `"pedestrian"`
  GT **only after** label_map canonicalization (guards the §5 fix).
- **Integration** (`test_tier3_real_grounding.py`, `importorskip` ml extra):
  a detection model through Tier 3 emits ≥20 canonicalized attributions →
  `status=measured`, evidence content-addressed; assert `latency_ms_per_image`
  **excludes** explain time (edge_profile unaffected).
- **Regression:** stub grounding path and all existing Tier-3 tests unchanged.
- **Live [HW]:** real `yolov8n.pt` on a **real road-scene golden set** produces a
  measured grounding score (see §8 dependency).

---

## 8. Risks & open questions

- **Data dependency (blocks an end-to-end demo):** a real model reaches Tier 3 only
  after clearing Tier 1 (`coco_ap_50_95 ≥ 0.25`) and Tier 2. On the *synthetic*
  sample, `yolov8n.pt` scored `0.2022` → rejected before Tier 3 ever runs. To
  actually *watch* a real model pass operational_safety we also need a **real
  Open-Images road-scene golden set** where the detector clears T1/T2
  (`scripts/fetch_open_images.py`). This feature makes the pass *possible*; the
  data makes it *reachable*.
- **Compute/latency window** — mitigated by bounded `N` + image cap + GPU.
- **D-RISE stochasticity** — reproducibility hinges on strict seeding; covered by the
  determinism unit test.
- **Grad-CAM fragility** — if chosen instead, it couples to Ultralytics internals and
  needs a gradient-enabled forward; deferred behind D-RISE for that reason.

### Open questions for review
1. Explainer default **off (opt-in)** or **on for detection**?
2. **Two-phase timing** (clean timed + explain untimed) vs single-job split timing?
3. **D-RISE** as primary (recommended) — or start with Grad-CAM for speed?
4. `N` masks default (256? 512?) and the per-run image cap?
5. Emit **both** `point` and `energy_inside`, or points only for the POC?

---

## 9. Rough task breakdown (post-approval)

- **Phase 0** design: `spec.md`, `plan.md`, `research.md` (D-RISE method + refs),
  `data-model.md` (attribution provenance), contract deltas.
- **Phase 1** tests-first: units + integration above (observed failing).
- **Phase 2** extractor: `engine/metrics/grounding_drise.py` (seeded masks, saliency,
  peak/energy) + wire into `_predict_det` explain path.
- **Phase 3** canonicalization fix (§5): thread `label_map` into Tier 3; extend
  `canonicalize()` to the attribution channel.
- **Phase 4** config + timing separation + Model Card surfacing of the method.
- **Phase 5** validation: full suite green, no regression; live [HW] on a real
  golden set; dual-bot review → merge.
