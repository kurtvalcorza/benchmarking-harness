#!/usr/bin/env python3
"""Generate the OWNED synthetic sample datasets committed under samples/.

Everything this script draws is procedurally generated here — no third-party
imagery, so the committed samples are license-clean by construction
(Constitution II). Deterministic (fixed seed) so regeneration is reproducible.

    python scripts/gen_samples.py

Layout produced:
    samples/benchmarks/open-images-det-sample/   # Tier-1 detection stand-in
    samples/benchmarks/open-images-cls-sample/   # Tier-1 classification stand-in
    samples/benchmarks/segmentation-sample/      # Tier-1 segmentation stand-in
    samples/golden/det-golden/                   # demo Golden Test Set (detection)
    samples/golden/cls-golden/                   # demo Golden Test Set (classification)
    samples/golden/seg-golden/                   # demo Golden Test Set (segmentation)
"""

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parents[1]
SAMPLES = REPO / "samples"
SEED = 20260710
SIZE = 96

# label → fill color; pedestrian is the safety-critical minority class
DET_CLASSES = {
    "vehicle": (60, 90, 200),
    "pedestrian": (200, 80, 60),
    "traffic_sign": (230, 200, 40),
}
CLS_CLASSES = {
    "vehicle": (60, 90, 200),
    "animal": (80, 180, 90),
    "building": (150, 120, 100),
}
# segmentation reuses the road-scene canonical vocabulary so one golden
# vocabulary serves detection + segmentation and pedestrian stays the
# safety-critical minority class (research.md R2).
SEG_CLASSES = DET_CLASSES
# model-emitted (COCO) → canonical (F6): a COCO-trained -seg model emits
# person/car/… ; written into the segmentation manifest so canonicalize()
# maps predictions onto the golden label space before scoring.
SEG_LABEL_MAP = {
    "person": "pedestrian",
    "car": "vehicle",
    "truck": "vehicle",
    "bus": "vehicle",
    "stop sign": "traffic_sign",
    "traffic light": "traffic_sign",
}


def _background(rng: np.random.Generator) -> Image.Image:
    base = rng.integers(120, 200)
    arr = rng.normal(base, 12, (SIZE, SIZE, 3)).clip(0, 255).astype(np.uint8)
    return Image.fromarray(arr)


def _draw_object(draw: ImageDraw.ImageDraw, rng: np.random.Generator, color) -> list[float]:
    w = int(rng.integers(18, 40))
    h = int(rng.integers(18, 40))
    x1 = int(rng.integers(2, SIZE - w - 2))
    y1 = int(rng.integers(2, SIZE - h - 2))
    draw.rectangle([x1, y1, x1 + w, y1 + h], fill=color, outline=(20, 20, 20))
    return [float(x1), float(y1), float(x1 + w), float(y1 + h)]


def gen_detection(root: Path, n_images: int, rng: np.random.Generator) -> None:
    (root / "images").mkdir(parents=True, exist_ok=True)
    labels = list(DET_CLASSES)
    ann: dict[str, list[dict]] = {}
    for i in range(n_images):
        img_id = f"det_{i:03d}"
        im = _background(rng)
        draw = ImageDraw.Draw(im)
        objs = []
        # every image gets 2-4 objects; pedestrians appear in ~half (minority class)
        n_obj = int(rng.integers(2, 5))
        for j in range(n_obj):
            label = "pedestrian" if (j == 0 and i % 2 == 0) else labels[int(rng.integers(0, 3))]
            bbox = _draw_object(draw, rng, DET_CLASSES[label])
            objs.append({"label": label, "bbox": bbox})
        ann[img_id] = objs
        im.save(root / "images" / f"{img_id}.png")
    (root / "annotations.json").write_text(json.dumps(ann, indent=1))


def gen_classification(root: Path, n_images: int, rng: np.random.Generator) -> None:
    (root / "images").mkdir(parents=True, exist_ok=True)
    labels = list(CLS_CLASSES)
    ann: dict[str, list[dict]] = {}
    for i in range(n_images):
        img_id = f"cls_{i:03d}"
        label = labels[i % len(labels)]
        im = _background(rng)
        draw = ImageDraw.Draw(im)
        _draw_object(draw, rng, CLS_CLASSES[label])
        ann[img_id] = [{"label": label}]
        im.save(root / "images" / f"{img_id}.png")
    (root / "annotations.json").write_text(json.dumps(ann, indent=1))


def _rle_encode(mask: np.ndarray) -> dict:
    """COCO-style RLE for a HxW binary mask (research.md R3). `counts` is stored
    as an ascii string so the annotation is plain JSON."""
    from pycocotools import mask as coco_mask

    r = coco_mask.encode(np.asfortranarray(mask.astype(np.uint8)))
    counts = r["counts"]
    return {
        "size": [int(r["size"][0]), int(r["size"][1])],
        "counts": counts.decode("ascii") if isinstance(counts, bytes) else counts,
    }


def _draw_seg_object(draw: ImageDraw.ImageDraw, rng: np.random.Generator, color) -> tuple[list[float], np.ndarray]:
    """Draw a filled ELLIPSE (so the pixel mask differs from its bounding box —
    bbox IoU must never stand in for mask IoU) and return (bbox, HxW mask)."""
    w = int(rng.integers(18, 40))
    h = int(rng.integers(18, 40))
    x1 = int(rng.integers(2, SIZE - w - 2))
    y1 = int(rng.integers(2, SIZE - h - 2))
    box = [x1, y1, x1 + w, y1 + h]
    draw.ellipse(box, fill=color, outline=(20, 20, 20))
    m = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(m).ellipse(box, fill=1)
    return [float(v) for v in box], np.array(m, dtype=np.uint8)


def gen_segmentation(root: Path, n_images: int, rng: np.random.Generator) -> None:
    (root / "images").mkdir(parents=True, exist_ok=True)
    labels = list(SEG_CLASSES)
    ann: dict[str, list[dict]] = {}
    for i in range(n_images):
        img_id = f"seg_{i:03d}"
        im = _background(rng)
        draw = ImageDraw.Draw(im)
        objs = []
        n_obj = int(rng.integers(2, 5))
        for j in range(n_obj):
            label = "pedestrian" if (j == 0 and i % 2 == 0) else labels[int(rng.integers(0, 3))]
            bbox, mask = _draw_seg_object(draw, rng, SEG_CLASSES[label])
            objs.append({"label": label, "bbox": bbox, "rle": _rle_encode(mask)})
        ann[img_id] = objs
        im.save(root / "images" / f"{img_id}.png")
    (root / "annotations.json").write_text(json.dumps(ann, indent=1))
    # F6: a COCO-vocabulary -seg model scores against the canonical labels
    (root / "manifest.json").write_text(json.dumps({"label_map": SEG_LABEL_MAP}, indent=1))


def main() -> int:
    rng = np.random.default_rng(SEED)
    gen_detection(SAMPLES / "benchmarks" / "open-images-det-sample", 16, rng)
    gen_classification(SAMPLES / "benchmarks" / "open-images-cls-sample", 15, rng)
    gen_detection(SAMPLES / "golden" / "det-golden", 20, rng)
    gen_classification(SAMPLES / "golden" / "cls-golden", 15, rng)
    # Segmentation draws from its OWN stream, appended after the existing calls,
    # so adding it leaves the committed det/cls sample bytes (and their pinned
    # checksums) byte-identical.
    seg_rng = np.random.default_rng(SEED + 1)
    gen_segmentation(SAMPLES / "benchmarks" / "segmentation-sample", 16, seg_rng)
    gen_segmentation(SAMPLES / "golden" / "seg-golden", 20, seg_rng)
    print(f"samples written under {SAMPLES}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
