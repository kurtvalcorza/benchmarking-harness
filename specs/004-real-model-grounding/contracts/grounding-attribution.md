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
  the adapter MUST NOT apply any dataset `label_map` itself (the map lives with the data).
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

## Tier scoping (FR-306a — review finding #1)

- The extractor MUST run **only in Tier 3**. `run_inference` is tier-agnostic, so an `explain:
  bool = False` parameter MUST be threaded through **both** its legs: the `spec` dict into
  `engine/sandbox/job.py::run(spec)` (where `adapter.predict()`/`explain()` run) **and** the
  T073 HTTP round-trip — which has a **client and a server**: `runner_client.run_remote()` sends
  `explain` in the body **and** `backend/runner/main.py`'s `RunRequest` + `POST /run` MUST accept
  and forward it (else Pydantic drops it and Tier-3 attribution silently no-ops under
  `HARNESS_RUNNER_URL`). Tier 1 and Tier 2 call with the default (`explain=False` → no
  attribution, no extractor cost), and only Tier 3 passes `explain=True`.
- Attribution is produced by a separate `adapter.explain(model, images, preds)` step — an
  **optional** member of the `InferenceAdapter` `Protocol`, invoked via
  `getattr(adapter, "explain", None)` (pytorch + stub implement it; ONNX/others skip) — **not**
  inside `predict()`, so it can be timed separately and skipped entirely when `explain=False`.
- `HARNESS_GROUNDING_EXPLAINER` selects *which* extractor Tier 3 uses; it MUST NOT by itself
  cause attribution to run in any tier.

## Determinism (FR-302, SC-004)

- D-RISE's mask stream is seeded from `weights_digest + image_id` (+ optional
  `HARNESS_DRISE_SEED` salt), independent of global RNG order. Identical (weights, image, seed)
  → identical masks → identical saliency → identical `point`/`energy_inside` → identical
  evidence digest.
- Grad-CAM has no RNG; deterministic given fixed weights/inputs.

## Timing (FR-308 — review finding #2)

- The **clean** detection pass is the sole source of `latency_ms_per_image`,
  `throughput_images_per_s`, and `edge_deployable`.
- Attribution is produced by a separately-timed `adapter.explain()` step in
  `engine/sandbox/job.py::run(spec)` (after the timed clean `predict()`), so `JobResult.timing`
  carries `predict_s` (clean) and `explain_s` (extractor) as distinct keys. `run_tier3` MUST
  derive the resource profile from `predict_s` **only**; `explain_s` MUST NOT appear in it.
- The mechanism MUST NOT change `predict()`'s return type; it is a separate `explain()` call
  (`InferenceAdapter` protocol addition, default no-op).
- For `explain=False`, the clean-pass timing MUST be byte-for-byte unchanged from today on
  every execution leg (`job.py` and `run_remote`).

## Budget (FR-309)

- The extractor explains only enough images to reach `HARNESS_GROUNDING_MIN_SAMPLES` (default
  20) target instances, then stops, and `log()`s the cap (images explained, targets reached).
  No silent truncation.

## Canonicalization (FR-305)

- `metrics.canonicalize()` MUST remap each attribution entry's `label` via a `label_map`
  (as it does for `labels`/`masks`); a non-dict/invalid entry passes through unchanged.
- The Tier-3 grounding path MUST evaluate over **canonicalized** attributions (not raw
  predictions), mirroring Tier 1's two-step sequence (`tier1_capability.py:53-55`):
  `[Prediction.from_dict(p) for p in job.predictions]` **then**
  `canonicalize(preds, dataset.manifest.get("label_map") or {})`. The `from_dict` step is
  required because `canonicalize()` takes `list[Prediction]` while `job.predictions` is raw
  `list[dict]` (review finding #4).
- The `label_map` MUST come from that benchmark dataset (`resolve(get_benchmark(model_class).dataset)`),
  **not** the Tier-2 Golden Set — Tier 3 scores a different dataset, so the Golden Set's
  `label_map` would map against the wrong vocabulary and reintroduce the false-fail. No
  `orchestrator.py` change is required; `run_tier3` already holds the dataset.

## Provenance (FR-311)

- The measured tier result + Model Card MUST record the extractor (`drise`/`gradcam`), its
  version and params, the evaluator `method`/`evaluator_version`/`sample_count`, and the
  resolvable `evidence_ref`/`evidence_digest`.

## Method semantics + docstring (review findings #5, #6)

- **#5 (FR-316):** the two evaluator methods define `sample_count` differently —
  `_pointing_game` counts GT target boxes, `_energy_inside_region` counts attribution entries —
  yet share `grounding_min_samples`. The default (`pointing_game` first) is unaffected; if
  `energy_inside_region` is ever configured primary, the min-samples semantics MUST be
  documented or the evaluator aligned to count targets.
- **#6:** `Prediction.attribution`'s dataclass docstring (`base.py:48-52`) currently describes
  attribution as *either* `{label, point}` *or* `{label, energy_inside}`; FR-303 emits the
  **combined** `{label, point, energy_inside}`. The docstring MUST be updated when FR-303 lands
  (the evaluator already tolerates both shapes).

## Invariants

- Classification/segmentation attribution is never produced — those classes stay
  `unavailable(unsupported_model_class)` (FR-314).
- The stub adapter's attribution (GT-space label, synthetic point) is unchanged.
