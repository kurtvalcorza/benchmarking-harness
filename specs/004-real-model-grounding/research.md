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

**Decision**: Add a separate `PyTorchAdapter.explain(model, images, preds)` step (an optional
`InferenceAdapter` protocol method — see R3/R8) that runs the configured extractor and appends
one `{label, point, energy_inside}` per detection to the existing `Prediction.attribution`
channel. It is invoked by `job.py` **only when `explain=True`** (Tier 3), separately from and
after the clean `predict()`. No `Prediction` envelope change — the channel already exists
(002 US5). *(Earlier drafts put the extractor inside `_predict_det`; the second-round review
showed that welds it into the shared, single-timed predict path — R3/R8 move it to a separate
`explain()` step so it stays Tier-3-only and separately timed.)*

**Rationale**: The attribution channel and its `to_dict`/`from_dict`, the sandbox
serialization boundary, the `GroundingEvidence` evaluator, and the content-addressed
evidence store are all already built for the stub; the real path only needs to *fill* the
channel — now via `explain()` rather than inside `predict()`. Minimal surface, maximal reuse.

**Alternatives**: keeping attribution inside `predict()` (welds it into every tier's timed
inference — rejected, R3/R8); a separate "explain" sandbox job/entrypoint (an extra sandbox
spin-up + model reload) — rejected: the `explain()` step inside the same `job.py` run reuses
the loaded model and keeps one job.

## R3. Timing separation — clean timed, explain untimed (concrete seam)

**Decision**: Keep the **clean** detection pass as the sole source of
`latency_ms_per_image`/`throughput`/`edge_deployable`, and make the explain step **timed
separately** via a dedicated `adapter.explain()` call. **Pinned mechanism (second-round
review):** rather than change `predict()`'s return type to carry timing, `job.py::run(spec)`
runs the timed clean `predict()` (→ `predict_s`, unchanged) and, when `spec["explain"]`, a
**separately-timed `adapter.explain(model, images, preds)`** (→ `explain_s`) that attaches
attribution to the predictions. `InferenceAdapter` is a `typing.Protocol` (`base.py:105`,
no default method bodies), so `explain()` is an **optional** member: `job.py` invokes it via
`getattr(adapter, "explain", None)` and skips when absent. Only the pytorch adapter (D-RISE/
Grad-CAM) and the stub (its synthetic attribution, moved out of `predict()`) implement it; ONNX
and any other adapter need no change. `run_tier3` derives the resource profile from `predict_s`
only.

**Rationale**: D-RISE adds `N` forward passes per image; folding that into latency would
wreck the edge-deployability signal and misrepresent the model. The resource profile must
describe the *model*, not the *explainer* (FR-308). **Review correction (#2):** the earlier
"runs separately and untimed" phrasing had no implementable seam — today `run_inference`
wraps the *whole* `predict()` in one `timing` block (`tier3_ops.py:76-88`), and attribution
(FR-301) is produced inside that call, so it would be counted. A concrete clean-vs-explain
**split** inside the timing block is the seam; it is a change to the `run_inference`/adapter
timing contract (not `orchestrator.py`), and for `explain=False` the clean-pass timing stays
byte-for-byte as today.

**Alternatives**: two separate `run_inference` calls in Tier 3 (one clean+timed, one
explain+untimed) — doubles sandbox spin-up + model load for no benefit; the single
`explain=True` call reusing the loaded model with split timing is cheaper and keeps the
clean detections and the attributions consistent.

## R8. Explainer scoped to Tier 3 via an `explain` seam (review finding #1)

**Decision**: Thread an `explain: bool = False` parameter through `run_inference` and **down
its full execution path** — not just the tier call-sites. `run_inference` (`runner.py:140`)
fans out to two legs, both of which must carry `explain` (second-round review): (a) the
serialized `spec` dict into `engine/sandbox/job.py::run(spec)` (subprocess/docker), which is
where `adapter.predict()` actually runs (`job.py:107`) and where `predict_s`/
`latency_ms_per_image` are built (`job.py:118-123`); and (b) the HTTP round-trip to the
dedicated runner service (the T073 path, when `HARNESS_RUNNER_URL` is set). The HTTP leg has a
**client and a server**, both of which must carry `explain` (third-round review): the client
`app/services/runner_client.py::run_remote()` sends it in the body, **and** the server
`backend/runner/main.py` must accept it — `RunRequest` (`main.py:49-53`) gains
`explain: bool = False` and `POST /run` (`main.py:76-90`) forwards it to its local
`run_inference(...)`. If the server side is missed, Pydantic silently drops the extra body field
and Tier-3 attribution **silently no-ops under `HARNESS_RUNNER_URL`** — a silent failure, worse
than the loud in-process one. Tier 1 and Tier 2 call with the default (no attribution, no
extractor cost); **only Tier 3** calls `explain=True`. The global `HARNESS_GROUNDING_EXPLAINER`
selects *which* extractor Tier 3 uses (`drise`/`gradcam`/`none`); it does **not** by itself cause
attribution to run.

**Rationale**: `run_inference` is tier-agnostic — the identical call is made in all three
tiers (`tier1_capability.py:39`, `tier2_stress.py:82`, `tier3_ops.py:62`) over one shared
adapter `predict()`, and attribution is consumed **only** by Tier 3's `_grounding_evidence`.
Gating the extractor on the global toggle alone would run D-RISE's ~`N` passes/image on every
Tier-1 inference and every Tier-2 perturbation condition (Tier 2 loops conditions), i.e. the
most expensive op in the harness running 3×+ with its output discarded in two tiers. The
`explain` seam is the minimal change that confines the cost to where the evidence is used.
It also composes cleanly with R3 (the same `explain=True` path is where clean-vs-explain
timing splits).

**Alternatives**: a per-tier config flag (leaks tier identity into config, still needs the
seam); detecting "am I Tier 3?" inside the adapter (adapter must stay tier-agnostic) — both
rejected in favor of an explicit `explain` argument on the call `run_tier3` already makes.

## R4. Attribution label canonicalization (F6) — the correctness fix

**Decision**: Attribution labels MUST be canonicalized through **the Tier-3-resolved
benchmark dataset's own `manifest.label_map`** **before** grounding is evaluated.
`metrics.canonicalize()` is extended to remap the `attribution` channel's labels (mirroring
the existing `labels`/`masks` remap), and `tier3_ops.run_tier3` canonicalizes the attributions
by **mirroring Tier 1's exact two-step sequence** (`tier1_capability.py:53-55`):
`preds = [Prediction.from_dict(p) for p in job.predictions]` **then**
`canonicalize(preds, dataset.manifest.get("label_map") or {})` — on the dataset it already
resolves at `tier3_ops.py:61`, before `_grounding_evidence` scores. The `from_dict` step is
required (review finding #4): `canonicalize()` takes `list[Prediction]` while `job.predictions`
is raw `list[dict]`, so calling it on the dicts directly would `AttributeError`; the attribution
channel round-trips through `from_dict`/`to_dict` (`base.py:65,79`).

**Rationale**: pointing_game matches `attribution.label == gt.label`, and GT is in the
canonical dataset vocabulary (`pedestrian`/`vehicle`) while a real COCO detector emits
`person`/`car`. Today Tier 3 builds attributions from **raw** `job.predictions` with no
canonicalization at all — so every foreign-vocabulary (i.e. real) detector would class-match
zero targets and false-fail. This is the single highest-risk correctness gap in the feature.
The stub path is unaffected (identity/absent `label_map`, GT-space attribution labels).

**Critical seam correction**: Tier 3 scores against `resolve(get_benchmark(model_class).dataset)`
— the **registry stand-in benchmark** (the same dataset Tier 1 scores `coco_ap_50_95` against),
**not** the Tier-2 Golden Set (`golden.data_ref`/`golden.label_map`, threaded via
`orchestrator.py`). The `label_map` MUST therefore come from that benchmark dataset's own
`manifest.json`, whatever it is (present in fetched `data/`; absent → a harmless no-op on the
bare synthetic sample, exactly like Tier 1). Threading the **Golden Set's** `label_map` would
canonicalize against a map keyed for a *different dataset's* vocabulary — it would *look* fixed
(canonicalization runs) while scoring against the wrong mapping, subtly reintroducing the
false-fail. Consequently `run_tier3` needs no new argument and **no `orchestrator.py` change**;
it canonicalizes from the `dataset` already in scope.

**Alternatives**: have the adapter emit attribution already in dataset space — rejected: the
adapter must not know any dataset's `label_map` (it lives with the *data*, not the model),
exactly as detection/classification labels are canonicalized downstream, not in the adapter.
Threading `golden.label_map` into Tier 3 — rejected per the seam correction above.

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
