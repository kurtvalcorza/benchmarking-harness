# Contract: Grounding Attribution Producer

The producer-side contract for Tier-3 visual grounding, complementing the evaluator-side
`002/contracts/metric-evidence.md §GroundingEvidence`. It defines what a real detection
adapter MUST emit so the existing pointing-game / energy-inside evaluators can MEASURE it.

## Attribution entry (adapter → `Prediction.attribution`)

One entry per emitted detection:

```json
{ "label": "person", "point": [634.0, 218.5], "energy_inside": 0.71 }
```

### Rules

- `label` is the detection's class in the **model-emitted vocabulary**. It is canonicalized
  to the dataset label space by `canonicalize()` **before** grounding is evaluated (FR-305) —
  the adapter MUST NOT apply the golden set `label_map` itself.
- `point` is `[x, y]` in **original-image pixel coordinates** — the same frame as the XYXY
  detection boxes the evaluator's `_inside()` compares against (FR-304). Both components finite.
- `energy_inside` is finite in `[0, 1]` — the fraction of the saliency map's energy that falls
  inside the detection's box (FR-303). An out-of-range value is `invalid_evidence` at the
  evaluator (existing rule), never clamped silently.
- The evidence MUST derive from a **real saliency method** over the model. It MUST NOT be
  approximated from confidence, entropy, parameter count, latency, throughput, or any adapter
  scalar (002 `metric-evidence.md §Forbidden substitutions`).

## Extractors

### D-RISE (default — `HARNESS_GROUNDING_EXPLAINER=drise`)

- Black-box: invokes **only** `model.net.predict` on masked in-memory image copies (no network,
  no auto-download, no new reads — FR-310).
- Per image: `N = HARNESS_DRISE_MASKS` (default 256) seeded low-res masks
  (`HARNESS_DRISE_MASK_RES`, default 16) upsampled + shifted; masks reused across all target
  detections in the image.
- Per target detection `d*`: weight each mask by `IoU(b*, b) · cos(p*, p) · objectness` of the
  best-matching masked detection; `S = Σ wᵢ·Mᵢ`; `point = argmax(S)`;
  `energy_inside = energy(S ∩ b*) / energy(S)`.

### Grad-CAM (selectable — `HARNESS_GROUNDING_EXPLAINER=gradcam`)

- Class-discriminative CAM over the detection head's last conv layer; `point = argmax(CAM)`,
  `energy_inside` computed identically. Same output envelope as D-RISE.
- A binding failure on an unsupported Ultralytics internal MUST surface as a clear infra reason
  (adapter/infra failure), never a silent wrong-region point (FR-307).

### `none`

- Emits no attribution → grounding is `unavailable(missing_attribution)` (the pre-004
  behavior, unchanged — FR-306).

## Determinism (FR-302, SC-004)

- D-RISE's mask stream is seeded from `weights_digest + image_id` (+ optional
  `HARNESS_DRISE_SEED` salt), independent of global RNG order. Identical (weights, image, seed)
  → identical masks → identical saliency → identical `point`/`energy_inside` → identical
  evidence digest.
- Grad-CAM has no RNG; deterministic given fixed weights/inputs.

## Timing (FR-308)

- The **clean** detection pass is the sole source of `latency_ms_per_image`,
  `throughput_images_per_s`, and `edge_deployable`. The explain phase runs **separately and
  untimed**; its cost MUST NOT appear in the resource profile.

## Budget (FR-309)

- The extractor explains only enough images to reach `HARNESS_GROUNDING_MIN_SAMPLES` (default
  20) target instances, then stops, and `log()`s the cap (images explained, targets reached).
  No silent truncation.

## Canonicalization (FR-305)

- `metrics.canonicalize()` MUST remap each attribution entry's `label` via the golden set
  `label_map` (as it does for `labels`/`masks`); a non-dict/invalid entry passes through
  unchanged.
- The Tier-3 grounding path MUST evaluate over **canonicalized** attributions (not raw
  predictions), so a foreign-vocabulary detector class-matches canonical GT.

## Provenance (FR-311)

- The measured tier result + Model Card MUST record the extractor (`drise`/`gradcam`), its
  version and params, the evaluator `method`/`evaluator_version`/`sample_count`, and the
  resolvable `evidence_ref`/`evidence_digest`.

## Invariants

- Classification/segmentation attribution is never produced — those classes stay
  `unavailable(unsupported_model_class)` (FR-314).
- The stub adapter's attribution (GT-space label, synthetic point) is unchanged.
