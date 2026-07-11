"""T040 (US3): invalid type, disk-full, and cleanup semantics.

Failed ingestion must leave no `.part` file, Model Version, or Artifact Receipt.
"""

import time

from app.services.artifact_ingest import (
    StagedArtifact,
    StorageFull,
    UnsupportedArtifactType,
    UploadTooLarge,
    stage_upload,
    staging_dir,
)
from app.services.artifact_janitor import sweep_abandoned
from app.services.config import load_config
from tests.conftest import bearer


class _RaisingReader:
    """A file object that fails mid-stream to simulate a disk/connection fault."""

    def __init__(self, chunks_before_error: int):
        self._left = chunks_before_error

    def read(self, n: int) -> bytes:
        if self._left <= 0:
            raise OSError(28, "No space left on device")
        self._left -= 1
        return b"x" * n


def test_wrong_extension_is_415(client):
    r = client.post(
        "/models",
        data={"name": "x", "model_class": "detection", "framework": "stub", "version": "v1"},
        files={"weights": ("weights.bin", b"{}", "application/octet-stream")},
        headers=bearer("s@example.com", ["submitter"]),
    )
    assert r.status_code == 415


def test_stage_disk_full_raises_and_cleans_up(monkeypatch, tmp_path):
    monkeypatch.setenv("HARNESS_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    cfg = load_config()
    reader = _RaisingReader(chunks_before_error=1)
    try:
        stage_upload(reader, "w.json", "stub", cfg)
        raise AssertionError("expected StorageFull")
    except StorageFull:
        pass
    # no .part left behind
    assert list(staging_dir(cfg).glob("*.part")) == []


def test_oversize_stream_leaves_no_part(monkeypatch, tmp_path):
    monkeypatch.setenv("HARNESS_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("HARNESS_MAX_UPLOAD_BYTES", "16")
    cfg = load_config()
    import io

    try:
        stage_upload(io.BytesIO(b"y" * 64), "w.json", "stub", cfg)
        raise AssertionError("expected UploadTooLarge")
    except UploadTooLarge:
        pass
    assert list(staging_dir(cfg).glob("*.part")) == []


def test_bad_extension_rejected_before_streaming(monkeypatch, tmp_path):
    monkeypatch.setenv("HARNESS_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    cfg = load_config()
    import io

    try:
        stage_upload(io.BytesIO(b"{}"), "model.exe", "stub", cfg)
        raise AssertionError("expected UnsupportedArtifactType")
    except UnsupportedArtifactType:
        pass


def test_janitor_sweeps_abandoned_parts(monkeypatch, tmp_path):
    monkeypatch.setenv("HARNESS_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    cfg = load_config()
    staging = staging_dir(cfg)
    staging.mkdir(parents=True, exist_ok=True)
    old = staging / "old.part"
    fresh = staging / "fresh.part"
    old.write_bytes(b"x")
    fresh.write_bytes(b"x")
    now = time.time()
    # age the old file well past the threshold
    import os

    os.utime(old, (now - 10_000, now - 10_000))
    removed = sweep_abandoned(cfg, older_than_seconds=3600, now=now)
    assert removed == 1
    assert not old.exists() and fresh.exists()


def test_staged_artifact_discard_is_idempotent(tmp_path):
    p = tmp_path / "x.part"
    p.write_bytes(b"x")
    s = StagedArtifact(temp_path=p, sha256="d", byte_count=1, original_filename="x.json")
    s.discard()
    s.discard()  # no error on second call
    assert not p.exists()
