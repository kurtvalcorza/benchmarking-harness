#!/usr/bin/env python3
"""Generate the OWNED synthetic sample datasets committed under samples/.

Everything this script draws is procedurally generated here — no third-party
imagery, so the committed samples are license-clean by construction
(Constitution II). Deterministic (fixed seed) so regeneration is reproducible.

    python scripts/gen_samples.py

Layout produced:
    samples/benchmarks/open-images-det-sample/   # Tier-1 detection stand-in
    samples/benchmarks/open-images-cls-sample/   # Tier-1 classification stand-in
    samples/golden/det-golden/                   # demo Golden Test Set (detection)
    samples/golden/cls-golden/                   # demo Golden Test Set (classification)
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


def main() -> int:
    rng = np.random.default_rng(SEED)
    gen_detection(SAMPLES / "benchmarks" / "open-images-det-sample", 16, rng)
    gen_classification(SAMPLES / "benchmarks" / "open-images-cls-sample", 15, rng)
    gen_detection(SAMPLES / "golden" / "det-golden", 20, rng)
    gen_classification(SAMPLES / "golden" / "cls-golden", 15, rng)
    print(f"samples written under {SAMPLES}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
