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
