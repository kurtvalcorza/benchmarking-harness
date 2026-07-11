"""T039 (US3): upload boundary + digest.

The limit is enforced on actual streamed bytes; the receipt carries the exact
byte count and SHA-256. `load_config` reads the environment per request, so the
test can shrink the limit after the client is built.
"""

import hashlib

from tests.conftest import bearer


def _submit(client, content: bytes, filename="w.json"):
    return client.post(
        "/models",
        data={"name": "up", "model_class": "detection", "framework": "stub", "version": "v1"},
        files={"weights": (filename, content, "application/json")},
        headers=bearer("submitter@example.com", ["submitter"]),
    )


def test_below_limit_succeeds_with_digest_receipt(client, monkeypatch):
    monkeypatch.setenv("HARNESS_MAX_UPLOAD_BYTES", "4096")
    content = b'{"kind":"stub-model","task":"detection","skill":0.9}'
    r = _submit(client, content)
    assert r.status_code == 201, r.text
    receipt = r.json()["artifact"]
    assert receipt["byte_count"] == len(content)
    assert receipt["sha256"] == hashlib.sha256(content).hexdigest()


def test_exactly_at_limit_succeeds(client, monkeypatch):
    monkeypatch.setenv("HARNESS_MAX_UPLOAD_BYTES", "1024")
    content = b"a" * 1024
    r = _submit(client, content)
    assert r.status_code == 201, r.text
    assert r.json()["artifact"]["byte_count"] == 1024


def test_above_limit_is_413_and_creates_no_state(client, monkeypatch):
    monkeypatch.setenv("HARNESS_MAX_UPLOAD_BYTES", "1024")
    r = _submit(client, b"a" * 1025)
    assert r.status_code == 413
    # no ModelVersion, receipt, or run was created
    from sqlmodel import Session, select

    from app.db.models import ArtifactReceipt, ModelVersion
    from app.db.repositories import get_engine

    with Session(get_engine()) as s:
        assert s.exec(select(ModelVersion)).all() == []
        assert s.exec(select(ArtifactReceipt)).all() == []
