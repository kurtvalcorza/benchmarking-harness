"""T020 — Constitution II gate: the tree contains no restricted datasets/weights.

Scans git-TRACKED files only (gitignored local data/ is expected and fine).
"""

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

FORBIDDEN_SUFFIXES = {".pt", ".pth", ".onnx", ".ckpt", ".safetensors", ".tar", ".tfrecord"}
FORBIDDEN_TOPDIRS = {"data", "datasets", "downloads", "weights", "models"}
# dataset names whose redistribution is restricted / non-commercial
RESTRICTED_NAMES = ("imagenet", "cityscapes", "culane", "wflw", "bdd100k")


def _tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout
    return [Path(line) for line in out.splitlines() if line]


def test_no_weight_or_archive_files_tracked():
    bad = [f for f in _tracked_files() if f.suffix.lower() in FORBIDDEN_SUFFIXES]
    assert not bad, f"restricted artifact types committed: {bad}"


def test_no_dataset_directories_tracked():
    bad = [f for f in _tracked_files() if f.parts and f.parts[0] in FORBIDDEN_TOPDIRS]
    assert not bad, f"dataset/weight directories must never be committed: {bad}"


def test_no_restricted_dataset_payloads_tracked():
    """Restricted dataset names may be *referenced* in code/docs, but no image
    payloads under such names may be committed."""
    image_suffixes = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
    for f in _tracked_files():
        if f.suffix.lower() not in image_suffixes:
            continue
        assert f.parts[0] == "samples", f"images may only be committed under samples/: {f}"
        assert not any(n in str(f).lower() for n in RESTRICTED_NAMES), (
            f"image committed under a restricted dataset name: {f}"
        )


def test_gitignore_blocks_data_and_weights():
    gitignore = (REPO / ".gitignore").read_text()
    for pattern in ("data/", "models/", "*.pt", "*.pth", "*.onnx"):
        assert pattern in gitignore, f".gitignore must block {pattern} (Constitution II)"
