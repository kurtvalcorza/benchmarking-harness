"""Dataset resolution + layout (FR-020: manifest-driven, no code change per set).

Layout of a conforming dataset directory:

    <dir>/
      manifest.json        # golden sets: name, model_class, version, conditions,
                           # safety_critical, recall_floors, license, is_public
      annotations.json     # {image_id: [{"label": str, "bbox": [x1,y1,x2,y2]?}]}
      images/<image_id>.png

Benchmarks and golden sets share this layout. Nothing here is committed except
owned/permissive samples/ (Constitution II); real data lands in $HARNESS_DATA_DIR
via scripts/fetch_*.
"""

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from engine.adapters.base import Image

REPO_ROOT = Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    return Path(os.environ.get("HARNESS_DATA_DIR", REPO_ROOT / "data"))


def samples_dir() -> Path:
    return Path(os.environ.get("HARNESS_SAMPLES_DIR", REPO_ROOT / "samples"))


@dataclass
class Dataset:
    root: Path

    @property
    def annotations(self) -> dict[str, list[dict]]:
        return json.loads((self.root / "annotations.json").read_text())

    @property
    def manifest(self) -> dict:
        p = self.root / "manifest.json"
        return json.loads(p.read_text()) if p.exists() else {}

    def images(self) -> list[Image]:
        img_dir = self.root / "images"
        return [
            Image(id=p.stem, path=str(p))
            for p in sorted(img_dir.iterdir())
            if p.suffix.lower() in (".png", ".jpg", ".jpeg")
        ]

    def labels(self) -> set[str]:
        return {obj["label"] for objs in self.annotations.values() for obj in objs}

    def checksum(self) -> str:
        """Content hash over annotations + image bytes (FR-018, Constitution IV)."""
        h = hashlib.sha256()
        h.update((self.root / "annotations.json").read_bytes())
        for img in self.images():
            h.update(Path(img.path).read_bytes())
        return h.hexdigest()


class DatasetNotFound(FileNotFoundError):
    pass


def validate_dataset(root: Path) -> list[str]:
    """Structural validation for a dataset dir (used at golden-set
    registration, FR-020): returns human-readable problems, empty when
    conforming. Catching malformed data HERE keeps a bad registration from
    crashing every later evaluation of its class."""
    problems: list[str] = []
    ann_path = root / "annotations.json"
    if not ann_path.exists():
        return [f"missing {ann_path.name}"]
    try:
        ann = json.loads(ann_path.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        return [f"annotations.json is not valid JSON: {e}"]
    if not isinstance(ann, dict):
        return ["annotations.json must map image id → list of objects"]
    for img_id, objs in ann.items():
        if not isinstance(objs, list):
            problems.append(f"annotations[{img_id!r}] must be a list")
            continue
        for i, obj in enumerate(objs):
            if not isinstance(obj, dict) or not isinstance(obj.get("label"), str):
                problems.append(f"annotations[{img_id!r}][{i}] needs a string 'label'")
                continue
            bbox = obj.get("bbox")
            if bbox is not None and not (
                isinstance(bbox, list)
                and len(bbox) == 4
                and all(isinstance(v, (int, float)) for v in bbox)
            ):
                problems.append(f"annotations[{img_id!r}][{i}].bbox must be [x1,y1,x2,y2]")
    ds = Dataset(root=root)
    image_ids = {img.id for img in ds.images()} if (root / "images").is_dir() else set()
    if not image_ids:
        problems.append("images/ is missing or contains no images")
    else:
        orphaned = sorted(set(ann) - image_ids)[:5]
        if orphaned:
            problems.append(f"annotated ids with no image file: {orphaned}")
        # unannotated files skew mAP (all predictions on them are FPs) and the
        # checksum; images with genuinely no objects must carry an empty list
        unannotated = sorted(image_ids - set(ann))[:5]
        if unannotated:
            problems.append(
                f"image files with no annotation entry (use [] for empty): {unannotated}"
            )
    return problems


def resolve(name_or_path: str) -> Dataset:
    """Resolve a dataset by absolute path, then $HARNESS_DATA_DIR/benchmarks/,
    then committed samples/benchmarks/ (owned/permissive stand-ins)."""
    candidates = [
        Path(name_or_path),
        data_dir() / "benchmarks" / name_or_path,
        samples_dir() / "benchmarks" / name_or_path,
    ]
    for c in candidates:
        if (c / "annotations.json").exists():
            return Dataset(root=c)
    raise DatasetNotFound(
        f"dataset '{name_or_path}' not found (looked in {[str(c) for c in candidates]}); "
        "fetch it via scripts/fetch_open_images.py or use the committed samples"
    )
