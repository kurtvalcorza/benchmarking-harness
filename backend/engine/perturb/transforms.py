"""Adverse-condition perturbations (T049, FR-008, Constitution II).

Self-contained PIL/NumPy implementations of rain / low_light / fog, applied to
owned/permissive data only — the repo never redistributes anything restricted.
When the `ml` extra is installed, imagecorruptions (Apache-2.0) and
albumentations (MIT) provide richer variants; these built-ins keep the harness
runnable everywhere and are deterministic (seeded) for SC-004.
"""

import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
from PIL import Image as PILImage

from app.db.enums import Condition


def _rng(seed_parts: str) -> np.random.Generator:
    # hashlib, not hash(): str hash is salted per process and would break SC-004
    digest = hashlib.sha256(seed_parts.encode()).digest()
    return np.random.default_rng(int.from_bytes(digest[:4], "big"))


def apply_condition(img: PILImage.Image, condition: Condition, seed: str = "") -> PILImage.Image:
    if condition is Condition.clean:
        return img
    arr = np.asarray(img.convert("RGB"), dtype=np.float32)
    if condition is Condition.low_light:
        out = arr * 0.35  # heavy exposure drop
    elif condition is Condition.fog:
        fog = np.full_like(arr, 235.0)
        out = 0.45 * arr + 0.55 * fog  # haze blend crushes contrast
    elif condition is Condition.rain:
        rng = _rng(f"rain|{seed}")
        out = arr * 0.8
        h, w = out.shape[:2]
        n_streaks = max(20, (h * w) // 400)
        xs = rng.integers(0, w, n_streaks)
        ys = rng.integers(0, max(1, h - 12), n_streaks)
        for x, y in zip(xs, ys, strict=True):
            length = int(rng.integers(6, 13))
            out[y : y + length, x] = out[y : y + length, x] * 0.4 + 255.0 * 0.6
    else:  # pragma: no cover - enum is closed
        raise ValueError(f"unknown condition {condition}")
    return PILImage.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def perturb_dataset(dataset_root: Path, condition: Condition, out_root: Path) -> Path:
    """Materialize a perturbed copy of a dataset (same layout, same image ids,
    annotations copied verbatim) so downstream scoring is unchanged (FR-008)."""
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "images").mkdir(exist_ok=True)
    shutil.copyfile(dataset_root / "annotations.json", out_root / "annotations.json")
    manifest = dataset_root / "manifest.json"
    if manifest.exists():
        meta = json.loads(manifest.read_text())
        meta["perturbed_condition"] = condition.value
        (out_root / "manifest.json").write_text(json.dumps(meta, indent=2))
    for img_path in sorted((dataset_root / "images").iterdir()):
        if img_path.suffix.lower() not in (".png", ".jpg", ".jpeg"):
            continue
        with PILImage.open(img_path) as im:
            perturbed = apply_condition(im, condition, seed=img_path.stem)
        perturbed.save(out_root / "images" / (img_path.stem + ".png"))
    return out_root
