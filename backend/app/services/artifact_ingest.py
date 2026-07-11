"""Bounded, hashed, atomic artifact ingestion (T041/T043, US3).

The upload is streamed to a `.part` file while counting bytes and hashing
SHA-256, and is aborted at the configured maximum regardless of any
`Content-Length` header (memory stays O(chunk)). Only after a clean stream is the
file atomically moved into place — so an oversized or interrupted upload can
never leave a partial artifact that becomes evaluable. Staging lives on the same
filesystem as the artifact root so the finalize rename is atomic.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.services.config import AppConfig

CHUNK = 1024 * 1024  # 1 MiB streaming chunk

# extension allow-list per framework; a mismatch is a 415 before any bytes land
_EXTENSIONS: dict[str, set[str]] = {
    "stub": {".json"},
    "pytorch": {".pt", ".pth"},
    "onnx": {".onnx"},
}


class UploadTooLarge(Exception):
    """Stream exceeded the configured maximum → 413."""


class UnsupportedArtifactType(Exception):
    """Filename extension does not match the declared framework → 415."""


class StorageFull(Exception):
    """The filesystem rejected the write (e.g. ENOSPC) → 507."""


@dataclass
class StagedArtifact:
    temp_path: Path
    sha256: str
    byte_count: int
    original_filename: str

    def discard(self) -> None:
        self.temp_path.unlink(missing_ok=True)


def staging_dir(cfg: AppConfig) -> Path:
    return cfg.artifacts_root / ".staging"


def _safe_name(filename: str | None) -> str:
    # strip path components so "../../x" cannot escape; default when empty
    return Path(filename or "").name or "weights.bin"


def _validate_extension(filename: str, framework: str) -> None:
    allowed = _EXTENSIONS.get(framework.lower())
    if allowed is None:
        return  # unknown frameworks are rejected earlier by SUPPORTED_FRAMEWORKS
    ext = Path(filename).suffix.lower()
    if ext not in allowed:
        raise UnsupportedArtifactType(
            f"'{ext or '(none)'}' is not a valid extension for framework "
            f"'{framework}' (expected one of {sorted(allowed)})"
        )


def stage_upload(fileobj, filename: str | None, framework: str, cfg: AppConfig) -> StagedArtifact:
    """Stream `fileobj` to a bounded `.part`, hashing as we go. Raises before any
    domain state is created; the caller finalizes only on success."""
    safe = _safe_name(filename)
    _validate_extension(safe, framework)

    staging = staging_dir(cfg)
    staging.mkdir(parents=True, exist_ok=True)
    part = staging / f"{uuid.uuid4().hex}.part"

    hasher = hashlib.sha256()
    total = 0
    try:
        with part.open("wb") as out:
            while True:
                chunk = fileobj.read(CHUNK)
                if not chunk:
                    break
                total += len(chunk)
                if total > cfg.max_upload_bytes:
                    raise UploadTooLarge(
                        f"upload exceeds the {cfg.max_upload_bytes}-byte limit"
                    )
                hasher.update(chunk)
                out.write(chunk)
    except UploadTooLarge:
        part.unlink(missing_ok=True)
        raise
    except OSError as e:
        part.unlink(missing_ok=True)
        raise StorageFull(f"failed to stage upload: {e}") from e

    return StagedArtifact(
        temp_path=part, sha256=hasher.hexdigest(), byte_count=total, original_filename=safe
    )


def finalize(staged: StagedArtifact, dest_dir: Path) -> Path:
    """Atomically move the staged file into `dest_dir`, returning its path.

    Same-filesystem `os.replace` is atomic: the destination never exists in a
    half-written state. On failure the staged file is removed by the caller's
    compensation.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = (dest_dir / staged.original_filename).resolve()
    if not dest.is_relative_to(dest_dir.resolve()):
        raise UnsupportedArtifactType("invalid artifact filename")
    try:
        os.replace(staged.temp_path, dest)
    except OSError as e:
        raise StorageFull(f"failed to finalize artifact: {e}") from e
    return dest
