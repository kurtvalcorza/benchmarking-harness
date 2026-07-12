# Data Model: Real-Model Visual Grounding for Tier 3

Entities and value objects added or changed for US1–US5. **No persisted schema change and
no Alembic migration** — grounding evidence reuses the existing content-addressed store and
the `GroundingEvidence` value object (002 US5).

## Value objects (engine, not persisted as tables)

### Prediction.attribution — filled by the real adapter (no shape change)

`engine.adapters.base.Prediction.attribution` already exists (002 US5) and is already carried
through `to_dict`/`from_dict` and the sandbox serialization boundary. This feature makes the
**real** detection adapter populate it; the entry shape is unchanged:

| Field | Type | Notes |
|---|---|---|
| `label` | `str` | the detection's class, in the **model-emitted** vocabulary (canonicalized downstream — see below) |
| `point` | `[float, float]` | saliency-map peak, **original-image pixel coordinates** (pointing_game input) — FR-304 |
| `energy_inside` | `float` | fraction of saliency energy inside the detection box, `[0,1]` (energy_inside_region input) — FR-303 |

An entry MAY carry either `point` or `energy_inside` or both; this feature emits **both**.
Finiteness/range rules are the existing grounding contract's (`point` finite; `energy_inside`
finite in `[0,1]` or the evaluator flags `invalid_evidence`).

### SaliencyMap (transient, not persisted)

Produced by an extractor per (image, detection), consumed immediately to derive `point` +
`energy_inside`, never persisted as pixels (Constitution II — evidence holds points/scalars,
not raw maps):

```
SaliencyMap = { "peak": [x, y], "energy_inside": float }   # the reduced, serializable form
```

The dense map exists only in memory during extraction.

### GroundingEvidence — unchanged contract, now reachable by real models

The existing frozen `GroundingEvidence` (002 `metric-evidence.md §GroundingEvidence`) is
reused verbatim. For a real measured detection run it now carries:

| Field | Value for a real measured run |
|---|---|
| `status` | `"measured"` |
| `method` | `"pointing_game"` (or `"energy_inside_region"`) — the *evaluator* method |
| `evaluator_version` | `"grounding/1"` (unchanged) |
| `score` | pointing-game hit-rate in `[0,1]` |
| `sample_count` | target instances scored (≥ `grounding_min_samples`) |
| `evidence_ref` / `evidence_digest` | content-addressed attribution artifact (existing store) |

The **extractor** identity (`drise`/`gradcam`) and its parameters are recorded alongside, so
provenance distinguishes *how the attribution was produced* from *which evaluator scored it*
(see EvaluatorProvenance-analogue below).

### Grounding extractor provenance (US5)

The measured Tier-3 result records, next to `GroundingEvidence`, the extractor provenance so a
pass is auditable and reproducible (FR-311):

```json
{
  "explainer": "drise",
  "explainer_version": "drise/1",
  "params": { "n_masks": 256, "mask_res": 16, "seed_basis": "weights_digest|image_id" }
}
```

This travels in the tier-result metrics (no new column) and is surfaced on the Model Card
grounding row.

## Persisted entities

**None changed.** No table, column, or migration is added:

- Grounding attribution evidence is written by the orchestrator's existing
  `_write_grounding_artifact` → `_write_content_addressed` under
  `results/evidence/<digest>.json` (content-addressed, append-only, reproducible).
- `GroundingEvidence.to_dict()` already carries method/version/score/sample_count/refs onto
  the append-only `TierResult.metrics`; the extractor provenance rides in the same dict.

## Config (not schema)

New environment configuration (FR-312), read by `app/services/config.py`:

| Env var | Default | Meaning |
|---|---|---|
| `HARNESS_GROUNDING_EXPLAINER` | `drise` | `drise` \| `gradcam` \| `none` — extractor for detection |
| `HARNESS_DRISE_MASKS` | `256` | D-RISE mask count `N` |
| `HARNESS_DRISE_MASK_RES` | `16` | low-res mask grid (upsampled to image size) |
| `HARNESS_DRISE_SEED` | `0` | optional extra salt folded into the per-image seed |

Reused unchanged: `HARNESS_GROUNDING_METHODS` (`pointing_game`, `energy_inside_region`),
`HARNESS_GROUNDING_MIN_SAMPLES` (`20`).

## `run_inference` / `JobResult.timing` — explain seam + timing split (not schema)

The explain seam touches the full execution path, not just `run_inference` (review #1/#2 +
2nd-round follow-up):

| Element | Change |
|---|---|
| `run_inference(..., explain: bool = False)` | new param (`runner.py`); forwarded to **both** legs — the `spec` dict → `job.py`, and the T073 HTTP round-trip. Tier 1/2 use the default, **only** Tier 3 passes `explain=True` (FR-306a) |
| T073 HTTP leg — **client + server** | `runner_client.run_remote()` sends `explain` in the body **and** `backend/runner/main.py` `RunRequest` (`:49-53`) gains `explain: bool = False` + `POST /run` (`:76-90`) forwards it; else Pydantic drops it and Tier-3 attribution silently no-ops under `HARNESS_RUNNER_URL` |
| `InferenceAdapter.explain(model, images, preds)` | **optional** member of the `Protocol` (`base.py:105`); `job.py` invokes via `getattr(adapter, "explain", None)`. pytorch + stub implement it; ONNX/others unchanged |
| `engine/sandbox/job.py::run(spec)` | reads `spec["explain"]`; after the timed clean `predict()` runs a **separately-timed** `explain()`; builds `predict_s`/`explain_s` |
| `JobResult.timing["predict_s"]` | the **clean** forward time (unchanged for `explain=False`) — the sole source of `latency_ms_per_image`/`throughput`/`edge_deployable` |
| `JobResult.timing["explain_s"]` | the extractor time, present only when `explain=True`; **not** folded into the resource profile (FR-308) |

No persisted schema change — these are transient `JobResult` fields on the sandbox boundary.

## Method-vs-sample_count note (FR-316, review finding #5)

`GroundingEvidence.sample_count` is defined differently by the two evaluator methods:
`_pointing_game` → GT target boxes; `_energy_inside_region` → attribution entries. Both gate
on `grounding_min_samples`. Under the default (`pointing_game` first) this is immaterial; if
`energy_inside_region` is configured primary, the min-samples bar changes meaning. Documented,
not changed, for this feature.

## Canonicalization (the F6 fix — FR-305)

`metrics.canonicalize()` today rebuilds `Prediction` remapping `labels`, `label`,
`class_scores`, and `masks` — **but not `attribution`**. It is extended to remap each
attribution entry's `label` via the `label_map` (non-dict/invalid entries pass through
unchanged, consistent with the mask-channel rule). `tier3_ops.run_tier3` — whose
`_grounding_evidence` today reads **raw** `job.predictions` — canonicalizes the attributions by
**mirroring Tier 1's two-step sequence** (`tier1_capability.py:53-55`):
`[Prediction.from_dict(p) for p in job.predictions]` **then**
`canonicalize(preds, dataset.manifest.get("label_map") or {})`, on the dataset it already
resolves at `tier3_ops.py:61`. The `from_dict` step is required — `canonicalize()` takes
`list[Prediction]`, `job.predictions` is `list[dict]` (review finding #4). Result: a `person`
attribution point inside a `pedestrian` box counts as a hit under that dataset's
`label_map {person: pedestrian}`.

**Seam (not the Golden Set):** Tier 3 scores against the **registry stand-in benchmark**
(`resolve(get_benchmark(model_class).dataset)`), not the Tier-2 Golden Set, so the `label_map`
comes from that benchmark dataset's `manifest.json`. `run_tier3` needs no new argument and
**no `orchestrator.py` change** — using `golden.label_map` here would map against a different
dataset's vocabulary and reintroduce the false-fail.

## Transaction boundaries (unchanged)

Grounding evidence publish + tier-result persistence reuse the existing atomic-completion
transaction (002 US4/US5). No new transaction shape; a lost/duplicate dispatch stays
idempotent because the evidence path is content-addressed (identical attribution → identical
digest → identical file).

## Invariants (unchanged)

- Classification/segmentation grounding remains `unavailable(unsupported_model_class)`.
- The ratified `grounding_score ≥ 0.30` gate, the `min_samples` floor, and the fail-closed
  `unavailable → adjudication` routing are untouched.
- The stub grounding path (identity `label_map`, GT-space attribution) is behavior-unchanged.
