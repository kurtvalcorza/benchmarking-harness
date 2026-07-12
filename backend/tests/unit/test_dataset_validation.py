"""Segmentation golden-set structural validation (FR-219).

A segmentation golden set must carry valid COCO-RLE masks whose declared (H, W)
matches the actual image. A mask that decodes at a *different* size than its
image would make coverage derive the wrong canvas from ground truth and then
flag every real model mask as `mask_dim_mismatch` — so registration must reject
it up front.
"""

import json

import numpy as np
from pycocotools import mask as coco_mask

from engine.datasets import validate_dataset


def _rle(arr: np.ndarray) -> dict:
    r = coco_mask.encode(np.asfortranarray(arr.astype(np.uint8)))
    return {"size": [int(r["size"][0]), int(r["size"][1])], "counts": r["counts"].decode("ascii")}


def _write_png(path, h: int, w: int) -> None:
    from PIL import Image as PILImage

    PILImage.fromarray(np.zeros((h, w, 3), np.uint8)).save(path)


def _make_dataset(tmp_path, mask: np.ndarray, img_h: int, img_w: int):
    (tmp_path / "images").mkdir()
    _write_png(tmp_path / "images" / "a.png", img_h, img_w)
    ann = {"a": [{"label": "vehicle", "rle": _rle(mask)}]}
    (tmp_path / "annotations.json").write_text(json.dumps(ann))
    return tmp_path


def test_rejects_gt_mask_whose_size_differs_from_the_image(tmp_path):
    wrong = np.zeros((4, 4), np.uint8)
    wrong[0:2, :] = 1  # a 4×4 mask …
    _make_dataset(tmp_path, wrong, img_h=8, img_w=8)  # … but the image is 8×8
    problems = validate_dataset(tmp_path, require_masks=True)
    assert any("image dimensions" in p for p in problems), problems


def test_accepts_gt_mask_matching_the_image_size(tmp_path):
    mask = np.zeros((8, 8), np.uint8)
    mask[0:4, :] = 1
    _make_dataset(tmp_path, mask, img_h=8, img_w=8)
    assert validate_dataset(tmp_path, require_masks=True) == []
