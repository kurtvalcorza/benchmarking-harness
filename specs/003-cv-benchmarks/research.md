# Research: Computer-Vision Capability Benchmarks

Design decisions for US4 (image segmentation). Each records the decision, the
rationale, and the alternatives considered. Retro stories US1–US3 needed no
research (delivered; see spec Delivery status).

## R1. Segmentation metric — semantic mIoU

**Decision**: Tier-1 capability = **semantic mean IoU (`miou`)**: for each registered
class, accumulate intersection and union **pixel counts** over the whole dataset,
compute per-class IoU = ∩ / ∪, and report `miou` = mean over classes plus the
per-class IoU map. Denominator is the registered dataset (missing prediction =
empty mask for that image, so it lowers IoU — the US2 complete-accounting rule).

**Rationale**: mIoU is the standard semantic-segmentation benchmark (the registry
already names Cityscapes mIoU). Dataset-level pixel accumulation (not mean of
per-image IoU) is the Cityscapes/PASCAL convention and is stable on small sets.

**Alternatives**: per-image mean IoU (unstable on tiny sets, non-standard);
instance mask-AP (COCO-style) — deferred (spec Out of scope): it needs matching
+ confidence sweeps and a different reference; mIoU is the POC standard.

## R2. Ground-truth source and license

**Decision**: Fetch a permissive **Open Images V7 segmentation** slice (masks) via
FiftyOne into gitignored `data/`, reusing the road-scene canonical vocabulary
already used for detection (`Person→pedestrian`, `Car→vehicle`, …) via a manifest
`label_map`. Ship an **owned synthetic** segmentation sample under `samples/` for
the offline demo and tests.

**Rationale**: Open Images V7 provides instance segmentation masks; its
annotations are CC-BY-4.0 and images individually CC-BY-2.0 — the same
licensing-clean, fetch-not-redistribute path already used for detection/
classification (Constitution II). Reusing the canonical label space lets one
golden vocabulary serve detection and segmentation.

**Alternatives**: COCO segmentation (annotations CC-BY-4.0 but image licenses are
heterogeneous — weaker licensing story); Cityscapes (registration-gated,
non-commercial — fails Constitution II). Open Images keeps the existing FiftyOne
tooling and license posture.

## R3. Mask representation on the wire and in evidence

**Decision**: **COCO-style RLE** (run-length encoding) — `{"size": [h, w],
"counts": "<rle>"}` — for both dataset annotations and predictions, using
`pycocotools.mask` (already a core dep from US2) to encode/decode and to compute
intersection/union. Polygons in a source are converted to RLE at fetch time.

**Rationale**: RLE is compact, lossless at the pixel level (polygons lose
boundary detail), deterministic as bytes (so mask evidence is content-addressed
and reproducible — SC-004), and `pycocotools.mask.merge/area/iou` operate on it
directly. No raw image pixels are embedded (Constitution II / evidence rules).

**Alternatives**: polygon lists (lossy, ambiguous fill rules); dense PNG masks
(large, non-canonical bytes across encoders — reproducibility risk).

## R4. Instance → semantic reduction (deterministic)

**Decision**: The `-seg` adapter emits **per-instance** masks (class, confidence,
RLE). The scorer reduces them to one **per-class semantic mask** per image
deterministically:
1. sort instances by `(confidence desc, instance_index asc)`;
2. paint pixels in that order into a single label map — the first (highest-conf)
   instance to claim a pixel owns it (cross-class overlap resolved by confidence);
3. union same-class instances; unclaimed pixels are background (unscored).

**Rationale**: mIoU is per-class semantic, so per-instance masks must reduce to a
per-class mask; a fixed ordering makes the reduction reproducible regardless of
adapter output order. Confidence-priority matches how overlapping predictions are
normally resolved.

**Alternatives**: naive per-class union with no overlap rule (double-counts a
pixel across classes, breaks IoU); argmax over per-class score maps (YOLO-seg
gives per-instance masks, not dense per-class logits).

## R5. Coverage and malformed-mask validation

**Decision**: Extend the coverage layer so a segmentation prediction set is
validated like classification/detection (expected = dataset size; missing =
empty mask counted; duplicate/extra = typed error) **and** each mask payload is
validated: RLE decodes, `size` equals the image dimensions, no negative/NaN
counts. A malformed mask is a **typed coverage error**, never a silent empty
score or a scorer crash.

**Rationale**: The US2 anti-inflation rule must hold for masks; masks add new
malformed cases the current label/bbox validator cannot catch (FR-216).

## R6. Per-class IoU floors and downstream verdict paths

**Decision**: Generalize the Tier-2 per-class safety floor from recall-only to a
**metric-typed floor**. Golden-set registration accepts per-class IoU floors;
`tier2_stress.py` checks them against per-class IoU for segmentation. The
recall-named downstream paths — the flag trigger `safety_critical_recall_below_floor`
/ `FlagInput.safety_recall_breach` and the Model Card wording — become
metric-appropriate (an IoU breach reads as an IoU breach).

**Rationale**: A segmentation scorer reports per-class IoU, not recall; leaving
the floor path recall-only would reject IoU-floor golden sets or flag every class
as missing recall (FR-214).

## R7. Mask evidence persistence

**Decision**: Persist the reduced per-class masks as **content-addressed
evidence** via the existing evidence store (stage → sha256 digest → atomic
publish → compensate on rollback), the same mechanism as grounding evidence.
Tier persistence today stores only metadata; segmentation adds the mask blob.

**Rationale**: FR-208/218 require mask evidence to be resolvable and reproducible;
reusing the US4/002 evidence store keeps append-only + digest guarantees.

## R8. Adapter — Ultralytics `-seg`, YOLO-first

**Decision**: The PyTorch adapter `segmentation` branch tries `YOLO()` first (same
pattern merged for classification in PR #11), requires `task == 'segment'`, and
reads `results[i].masks` (+ `.boxes` for class/confidence). A non-`segment`
checkpoint under the segmentation class is rejected clearly. A stub-seg adapter
emits deterministic masks from ground truth for the offline/test path.

**Rationale**: Consistency with detection/classification; Ultralytics owns the
compat/loader path and is already in the sandbox image. ONNX `-seg` is a
follow-up (the pytorch path is the reference).

## R9. Submission allowlist

**Decision**: Add `segmentation` to `engine.metrics.SCORED_CLASSES` and accept it
in the `app/api/models.py` submission guard; update the scorerless-class contract
test.

**Rationale**: The guard rejects any class not in `SCORED_CLASSES` with `422`
before inference, so removing `NotImplementedError` from `evaluate()` is necessary
but not sufficient (FR-213).

## Open items deferred (not blocking the build)

- Instance mask-AP (COCO-style) as a second segmentation metric — follow-up.
- ONNX `-seg` adapter path — follow-up (pytorch is the reference).
- Ratifying the numeric `miou` threshold — governance action; the build ships the
  slot + the fail-safe adjudication routing, not the ratified value.
