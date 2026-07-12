#!/usr/bin/env python3
"""Fetch a permissively licensed Open Images subset into data/ (NEVER committed).

Uses FiftyOne (part of the backend `ml` extra) to download a small Open Images
V7 slice under its own terms (annotations CC BY 4.0; images individually
CC BY 2.0). The result is written to $HARNESS_DATA_DIR (gitignored) in the
harness dataset layout (images/ + annotations.json) — see Constitution II and
DATASETS.md: datasets are fetched, not redistributed.

    python scripts/fetch_open_images.py --class detection --n 200
    python scripts/fetch_open_images.py --class classification --n 150

Offline fallback: --synthetic copies the owned synthetic samples instead, so
the full pipeline can be exercised with no network at all.
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

CLASS_TO_BENCH = {
    "detection": "open-images-det-sample",
    "classification": "open-images-cls-sample",
    "segmentation": "segmentation-sample",
}
# a small, road-scene-flavored label slice for the POC
DET_LABELS = ["Car", "Person", "Traffic sign"]
CLS_LABELS = ["Car", "Animal", "Building"]
# Open Images segmentation masks are available for a subset of classes; reuse the
# road-scene canonical vocabulary so one golden vocabulary serves det + seg.
SEG_LABELS = ["Car", "Person"]
# per-class canon maps: keeping these separate stops detection-only labels
# (Person/Traffic sign) leaking into classification datasets and vice versa
DET_CANON = {
    "Car": "vehicle",
    "Person": "pedestrian",
    "Traffic sign": "traffic_sign",
}
CLS_CANON = {
    "Car": "vehicle",
    "Animal": "animal",
    "Building": "building",
}
SEG_CANON = {
    "Car": "vehicle",
    "Person": "pedestrian",
}
# model-emitted → canonical (F6): lets COCO-trained detectors (YOLO et al.)
# score against the canonical label space; written into manifest.json
COCO_LABEL_MAP = {
    "person": "pedestrian",
    "car": "vehicle",
    "truck": "vehicle",
    "bus": "vehicle",
    "stop sign": "traffic_sign",
    "traffic light": "traffic_sign",
}


def _label_types(model_class: str) -> list[str]:
    return {
        "detection": ["detections"],
        "classification": ["classifications"],
        "segmentation": ["segmentations"],
    }[model_class]


def _seg_objects(sample, w: int, h: int) -> list[dict]:
    """Convert Open Images instance segmentations to full-image COCO-RLE masks.

    FiftyOne stores each instance's mask as a bbox-local boolean array; we paint
    it into a full-image canvas and RLE-encode (research.md R3). No raw image
    pixels are embedded (Constitution II)."""
    import numpy as np

    from engine.metrics.segmentation import rle_encode

    field = sample.ground_truth or getattr(sample, "segmentations", None)
    objs: list[dict] = []
    if not field:
        return objs
    for det in field.detections:
        if det.label not in SEG_CANON or det.mask is None:
            continue
        x, y, bw, bh = det.bounding_box  # relative xywh
        canvas = np.zeros((h, w), dtype=np.uint8)
        x0, y0 = int(round(x * w)), int(round(y * h))
        mask = np.asarray(det.mask).astype(np.uint8)
        mh, mw = mask.shape[:2]
        # clip the bbox-local mask into the image bounds
        y1, x1 = min(y0 + mh, h), min(x0 + mw, w)
        canvas[y0:y1, x0:x1] = mask[: y1 - y0, : x1 - x0]
        if canvas.any():
            objs.append(
                {
                    "label": SEG_CANON[det.label],
                    "bbox": [x * w, y * h, (x + bw) * w, (y + bh) * h],
                    "rle": rle_encode(canvas),
                }
            )
    return objs


def fetch_real(model_class: str, n: int, out: Path) -> None:
    import fiftyone.zoo as foz  # ml extra

    labels = {"detection": DET_LABELS, "classification": CLS_LABELS, "segmentation": SEG_LABELS}[
        model_class
    ]
    ds = foz.load_zoo_dataset(
        "open-images-v7",
        split="validation",
        label_types=_label_types(model_class),
        classes=labels,
        max_samples=n,
        shuffle=False,  # deterministic slice (Constitution IV)
    )
    images_dir = out / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    ann: dict[str, list[dict]] = {}
    for i, sample in enumerate(ds):
        img_id = f"oi_{i:04d}"
        src = Path(sample.filepath)
        shutil.copyfile(src, images_dir / f"{img_id}{src.suffix.lower()}")
        objs = []
        # fiftyone's open-images-v7 zoo loader stores detections in `ground_truth`
        if model_class == "detection" and sample.ground_truth:
            from PIL import Image

            with Image.open(src) as im:
                w, h = im.size
            for det in sample.ground_truth.detections:
                if det.label not in DET_CANON:
                    continue
                x, y, bw, bh = det.bounding_box  # relative xywh
                objs.append(
                    {
                        "label": DET_CANON[det.label],
                        "bbox": [x * w, y * h, (x + bw) * w, (y + bh) * h],
                    }
                )
        elif model_class == "segmentation":
            from PIL import Image

            with Image.open(src) as im:
                w, h = im.size
            objs = _seg_objects(sample, w, h)
        elif model_class == "classification" and sample.positive_labels:
            for c in sample.positive_labels.classifications:
                if c.label in CLS_CANON:
                    objs = [{"label": CLS_CANON[c.label]}]
                    break
        ann[img_id] = objs
    (out / "annotations.json").write_text(json.dumps(ann, indent=1))
    if model_class in ("detection", "segmentation"):
        # a COCO-vocabulary model (YOLO det/-seg) scores against the canonical labels
        (out / "manifest.json").write_text(json.dumps({"label_map": COCO_LABEL_MAP}, indent=1))


def fetch_synthetic(model_class: str, out: Path) -> None:
    src = REPO / "samples" / "benchmarks" / CLASS_TO_BENCH[model_class]
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(src, out)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--class", dest="model_class", choices=list(CLASS_TO_BENCH), required=True)
    p.add_argument("--n", type=int, default=200)
    p.add_argument(
        "--synthetic",
        action="store_true",
        help="copy the owned synthetic samples instead of downloading (offline demo)",
    )
    args = p.parse_args()

    out = REPO / "data" / "benchmarks" / CLASS_TO_BENCH[args.model_class]
    if out.exists():
        # a stale, larger previous fetch would contaminate images/ and the
        # checksum (FR-018) — always start from a clean slate
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    if args.synthetic:
        fetch_synthetic(args.model_class, out)
    else:
        try:
            fetch_real(args.model_class, args.n, out)
        except ImportError:
            print("fiftyone not installed (pip install 'backend[ml]'); use --synthetic for offline")
            return 1
    print(f"dataset written to {out} (gitignored — never commit datasets)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
