# Quickstart and Validation: Real-Model Grounding

Exercises US1–US5 end-to-end once implemented. Tier-3 grounding for the **stub** path is
already covered by 002 US5; this adds the **real detection** path.

## Prerequisites

```bash
pip install -e "backend[ml]"          # torch + ultralytics + numpy
# the running stack (compose) or the offline inline path
```

## 1. Confirm the explainer default

```bash
# detection grounding runs D-RISE by default; no config needed for the happy path.
# to disable / switch:
export HARNESS_GROUNDING_EXPLAINER=drise      # default | gradcam | none
export HARNESS_DRISE_MASKS=256                # optional; bounds cost
```

> **Cost note (on-by-default):** D-RISE adds roughly `N × (images needed to reach
> grounding_min_samples targets)` extra forward passes to a Tier-3 run — with the defaults
> `N=256`, ~20 targets, that's on the order of a few thousand nano-detector forward passes
> (~1–2 min on the RTX 5070 Ti reference), bounded (FR-309) and configurable via
> `HARNESS_DRISE_MASKS`. The first time a real detector reaches Tier 3 it will take
> noticeably longer than a stub run; set `HARNESS_GROUNDING_EXPLAINER=none` to skip it.

## 2. Submit a real detection model

```bash
# yolov8n.pt via the UI (class=detection, framework=pytorch) or:
curl -s -X POST http://localhost:8000/models -H "Authorization: Bearer $TOK" \
  -F name=yolov8n -F model_class=detection -F framework=pytorch -F version=v1 \
  -F declared_sources='COCO (Ultralytics YOLOv8n)' \
  -F weights=@yolov8n.pt
```

> Reachability (FR-315): the model must clear Tier 1 (`coco_ap_50_95 ≥ 0.25`) and Tier 2 on
> the golden set before Tier 3 runs. On the synthetic sample `yolov8n.pt` scores ~0.20 and is
> rejected first — to *watch* a real model reach a measured Tier 3, register a **real Open
> Images road-scene** golden set where the detector clears capability.

## 3. Validate measured grounding (US1)

- Tier 3 reports `grounding.status == "measured"` with `method == "pointing_game"`,
  `sample_count ≥ 20`, and a `grounding_score` in `[0,1]` — **not**
  `unavailable(missing_attribution)`.
- A well-grounded detector clears `grounding_score ≥ 0.30`; a poorly-grounded one routes to
  `pending_adjudication` (fail-closed unchanged).

## 4. Validate determinism (US1, SC-004)

```bash
# re-run the same model on the same golden set; the grounding evidence digest is identical.
cd backend && pytest tests/unit/test_grounding_drise.py -k determinism -q
```

## 5. Validate label canonicalization (US2, the F6 fix)

- A COCO detector emits attribution on `person`; with `label_map {person: pedestrian}` a point
  inside the `pedestrian` box is a **hit**. Without canonicalization the same input is a miss
  (the guard test asserts both).

```bash
cd backend && pytest tests/unit/test_grounding_canon.py -q
```

## 6. Validate timing honesty (US4)

- `latency_ms_per_image` / `edge_profile` for a run **with** the explainer match the clean pass
  — the explain phase is excluded from the resource profile.
- The run explains only enough images to reach `grounding_min_samples` and **logs** the cap.

```bash
cd backend && pytest tests/integration/test_tier3_real_grounding.py -k timing -q
```

## 7. Validate provenance (US5)

- The tier result + Model Card carry the extractor (`drise`/`gradcam`), evaluator version,
  sample count, and a resolvable `evidence_ref` whose sha256 equals `evidence_digest`.

## 8. Live sandbox probe

```bash
cd backend && pytest tests/integration/test_sandbox_runtime.py -k grounding -q
#   real yolov8n.pt emits D-RISE attribution inside the --network none sandbox;
#   masks survive the result.json serialization boundary.
```

## 9. Gates

```bash
cd backend && pytest -q            # full suite, incl. new grounding tests
make gates                         # constitution gates stay green (FR-314)
```

## Acceptance record

Record the live run (golden set checksum, extractor, `grounding_score`, method, sample_count,
evidence digest, verdict) in `specs/004-real-model-grounding/validation.md` on landing,
mirroring 002/003's validation records. Note the FR-315 data dependency if a real
end-to-end operational_safety pass is deferred to an [HW] follow-up.
