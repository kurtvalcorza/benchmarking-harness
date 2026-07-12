# Quickstart and Validation: Segmentation Benchmark

Exercises US4 end-to-end once implemented. Detection/classification quickstarts
are in feature 001/002; US1–US3 need no new steps (compose default-up, the Models
page, and yolov8n-cls loading all work on `main`).

## Prerequisites

```bash
pip install -e "backend[ml]"          # torch + ultralytics + pycocotools + fiftyone
# the running stack (compose) or the offline inline path
```

## 1. Fetch a permissive segmentation slice (masks)

```bash
python scripts/fetch_open_images.py --class segmentation --n 50
#   → data/benchmarks/open-images-seg-sample/{images,annotations.json,manifest.json}
#   annotations carry RLE masks; manifest carries the COCO→canonical label_map.
# offline: --synthetic copies the owned synthetic segmentation sample.
```

## 2. Register the segmentation golden set (masks + IoU floors)

```bash
python scripts/register_golden_set.py --class segmentation \
  --data /srv/data/benchmarks/open-images-seg-sample --license cc-by-4.0
#   safety_critical: [pedestrian], iou_floors: {pedestrian: 0.4}
#   registration REJECTS a dataset lacking valid masks (FR-219).
```

## 3. Submit a segmentation model

```bash
# yolov8n-seg.pt via the UI (class=segmentation, framework=pytorch) or:
curl -s -X POST http://localhost:8000/models -H "Authorization: Bearer $TOK" \
  -F name=yolov8n-seg -F model_class=segmentation -F framework=pytorch -F version=v1 \
  -F declared_sources='COCO (Ultralytics YOLOv8n-seg)' \
  -F weights=@yolov8n-seg.pt
#   accepted (not 422) because segmentation is on SCORED_CLASSES (FR-213).
```

## 4. Validate mIoU scoring

- The run scores `miou` + `per_class_iou`; a below-threshold `miou` rejects at
  capability (parallel to detection), an unratified threshold routes to
  `pending_adjudication` (FR-207).
- Verify per-class IoU floors are checked against **IoU** (not recall); an
  IoU-floor breach flags with an IoU trigger (FR-214).

## 5. Validate coverage + malformed masks

- A missing prediction counts as an empty mask (lowers IoU); a malformed RLE /
  dimension mismatch is a typed coverage error, not a silent empty score (FR-216).

## 6. Validate evidence

- The tier result carries `coverage` + `evaluator` (`segmentation-miou`) +
  `dataset_checksum`; the reduced per-class masks are content-addressed under
  `evidence/<digest>.json` and reproduce identically on re-run (SC-004, FR-218).

## 7. Live sandbox probe

```bash
cd backend && pytest tests/integration/test_sandbox_runtime.py -k segmentation -q
#   real yolov8n-seg.pt loads + emits masks inside the --network none sandbox.
```

## 8. Gates

```bash
cd backend && pytest -q            # full suite, incl. new segmentation tests
make gates                         # constitution gates stay green (FR-212)
```

## Acceptance record

Record the live run (golden set checksum, `miou`, per-class IoU, verdict) in
`specs/003-cv-benchmarks/validation.md` on landing (T061), mirroring 002's
validation record.
