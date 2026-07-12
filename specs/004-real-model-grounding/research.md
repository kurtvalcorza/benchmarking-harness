# Research: Real-Model Visual Grounding for Tier 3

Design decisions for US1–US5 (real-model attribution for detection). Each records the
decision, rationale, and alternatives considered.

## R1. Attribution method — D-RISE primary, Grad-CAM selectable

**Decision**: Ship **D-RISE** (Petsiuk et al. 2021, *Black-box Explanation of Object
Detectors via Saliency Maps*) as the default extractor, and **Grad-CAM** as a selectable
alternative (`HARNESS_GROUNDING_EXPLAINER=gradcam`). Both emit the same
`{label, point, energy_inside}` envelope.

D-RISE procedure, per image:
1. generate `N` seeded low-resolution binary masks; upsample + random-shift to image size;
2. run the detector on each masked image (the **existing** `.predict` path);
3. for a target detection `d*` (box `b*`, class `c*`, score-vector `p*`), weight each mask
   by the **detection-vector similarity** of the best-matching masked detection:
   `w = IoU(b*, b) · cos(p*, p) · objectness`;
4. saliency `S = Σ wᵢ · Mᵢ`, normalized. `peak(S) → point`; `energy(S restricted to b*) /
   energy(S) → energy_inside`.

**Rationale**:
- **Respects the adapter black-box boundary** — D-RISE only calls `model.net.predict` on
  masked copies, so it is robust across Ultralytics releases (the classification/segmentation
  loaders already lean on this boundary; a layer-hooking method is version-fragile).
- **Per-detection and class-discriminative by construction** — the target vector is a
  specific detection's box+class, so the saliency is for *that* detection's *class* — real
  pointing-game semantics, not a proxy (satisfies `metric-evidence.md §Forbidden
  substitutions`).
- **Deterministic** under a seeded mask stream (R5) → reproducible evidence (SC-004).
- **Feeds both approved methods** from one map — the peak for `pointing_game`, the box-energy
  fraction for `energy_inside_region`.

**Alternatives**:
- **EigenCAM** — class-agnostic (principal component of feature maps); its peak is not
  class-specific, so it cannot honor the class-matched pointing game. Rejected as primary.
- **Grad-CAM / Grad-CAM++** — class-discriminative and cheap (one backward pass per
  detection), but couples to Ultralytics internals (which layer, a gradient-enabled forward
  distinct from `predict()`'s inference mode) → version-fragile. Kept as a **selectable
  alternative** (US3), not the default.

## R2. Where the extractor plugs in

**Decision**: Extend `PyTorchAdapter._predict_det` with an opt-in **explain** step (default
on for detection). After the normal detections are collected, if the explainer is enabled
the adapter runs the configured extractor and appends one
`{label, point, energy_inside}` per detection to the existing `Prediction.attribution`
channel. No `Prediction` envelope change — the channel already exists (002 US5).

**Rationale**: The attribution channel and its `to_dict`/`from_dict`, the sandbox
serialization boundary, the `GroundingEvidence` evaluator, and the content-addressed
evidence store are all already built for the stub; the real path only needs to *fill* the
channel. Minimal surface, maximal reuse.

**Alternatives**: a separate "explain" sandbox job/entrypoint (more sandbox invocations,
more orchestration) — deferred; the in-adapter explain step with two-phase timing (R3) keeps
one job.

## R3. Timing separation — clean timed, explain untimed

**Decision**: Keep the **clean** detection pass as the sole source of
`latency_ms_per_image`/`throughput`/`edge_deployable` (as today), and run the explain step in
a **separate, untimed** phase. The adapter times only the clean forward; explain time is
reported under a distinct key that Tier 3 does **not** fold into the resource profile.

**Rationale**: D-RISE adds `N` forward passes per image; folding that into latency would
wreck the edge-deployability signal and misrepresent the model. The resource profile must
describe the *model*, not the *explainer* (FR-308).

**Alternatives**: single-job split timing (adapter reports a clean-vs-explain split and Tier 3
uses only the clean split) — viable but couples the timing contract more tightly; the
two-phase separation is simpler and keeps the clean-pass timing byte-for-byte as today.

## R4. Attribution label canonicalization (F6) — the correctness fix

**Decision**: Attribution labels MUST be canonicalized through the golden set `label_map`
**before** grounding is evaluated. `metrics.canonicalize()` is extended to remap the
`attribution` channel's labels (mirroring the existing `labels`/`masks` remap), and
`tier3_ops._grounding_evidence` is threaded the `label_map` and evaluates over
**canonicalized** attributions.

**Rationale**: pointing_game matches `attribution.label == gt.label`, and GT is in the
canonical dataset vocabulary (`pedestrian`/`vehicle`) while a real COCO detector emits
`person`/`car`. Today Tier 3 builds attributions from **raw** `job.predictions` with no
canonicalization at all — so every foreign-vocabulary (i.e. real) detector would class-match
zero targets and false-fail. This is the single highest-risk correctness gap in the feature.
The stub path is unaffected (identity `label_map`, GT-space attribution labels).

**Alternatives**: have the adapter emit attribution already in dataset space — rejected: the
adapter must not know the golden set's `label_map` (it lives with the *data*, not the model),
exactly as detection/classification labels are canonicalized downstream, not in the adapter.

## R5. Determinism — seeded mask stream

**Decision**: Seed the D-RISE mask generator from a hash of `weights_digest + image_id`
(e.g. `numpy.random.default_rng(int.from_bytes(sha256(f"{weights_digest}|{image_id}").digest()[:8], "big"))`),
independent of global torch RNG ordering. Same weights + same image → same masks → same
saliency → same attribution → same evidence digest.

**Rationale**: SC-004 requires evidence to reproduce byte-identically across reruns; a
per-image deterministic seed also makes the extraction order-independent (parallel-safe).
Grad-CAM has no RNG and is deterministic given fixed weights/inputs.

**Alternatives**: a single global seed (`torch.manual_seed`) — fragile: reproducibility would
depend on image iteration order and any intervening RNG use. Per-image seeding is robust.

## R6. Compute budget — bounded, logged

**Decision**: Explain only enough images to reach `grounding_min_samples` (default 20) target
instances, then stop; `log()` the cap (how many images explained, how many targets reached).
Default `N = HARNESS_DRISE_MASKS = 256`, mask resolution `HARNESS_DRISE_MASK_RES = 16` (16×16
upsampled). Masks are per-image and reused across all target detections in that image.

**Rationale**: D-RISE cost ≈ `N × (#images to reach min_samples)`. Bounding to the sample
minimum keeps a large golden set from running unboundedly; `N=256` is the low end of the
D-RISE paper's useful range and adequate for peak localization on a nano detector. The cap is
logged so coverage is honest (no silent truncation).

**Alternatives**: explain the whole golden set (unbounded cost, no accuracy gain past the
sample minimum); `N=4000` as in the paper's high-fidelity setting (unnecessary for peak/energy
on a POC — configurable via `HARNESS_DRISE_MASKS` for anyone who wants it).

## R7. Default on for detection

**Decision**: The extractor is **on by default for detection** (`HARNESS_GROUNDING_EXPLAINER`
defaults to `drise`); `none` disables it (restoring `missing_attribution`), `gradcam` selects
the alternative. Classification/segmentation ignore the setting (they stay
`unsupported_model_class`).

**Rationale**: The point of the feature is that a capable real detector *auto-passes* Tier 3
without extra operator ceremony; opt-in would leave real models stuck in adjudication by
default. The untimed/bounded design (R3/R6) keeps the default's cost from harming the
resource profile or running away.

**Alternatives**: opt-in default-off (safer on cost, but defeats the feature's purpose for the
default operator) — rejected; the bounded/untimed design mitigates the cost concern.

## Open items deferred (not blocking the build)

- ONNX detection attribution — follow-up (the PyTorch/Ultralytics path is the reference).
- Grad-CAM++ / higher-fidelity D-RISE (`N≈4000`) tuning — configurable, not a default.
- The **real road-scene golden set** where a real detector clears Tier 1/2 so it *reaches*
  Tier 3 — a data/[HW] step (FR-315), not a code deliverable; the measurement path is what
  this feature ships.
