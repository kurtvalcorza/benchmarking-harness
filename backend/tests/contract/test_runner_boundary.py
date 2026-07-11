"""US6 runner-service boundary auth (T073/T074 hardening).

The dedicated runner is the only component holding the container runtime socket,
so its /run endpoint MUST fail closed without a shared secret and reject a wrong
token (via a constant-time compare). /healthz stays public.
"""

import pytest
from fastapi.testclient import TestClient

from engine.sandbox.runner import JobResult
from runner import main as runner_main

VALID_BODY = {
    "framework": "stub",
    "model_class": "detection",
    "artifact": "/srv/samples/models/healthy_detector.stub.json",
    "dataset_root": "/srv/samples/golden/det-golden",
}


@pytest.fixture()
def client():
    return TestClient(runner_main.app)


def test_healthz_is_public(client):
    assert client.get("/healthz").json() == {"ok": True}


def test_run_fails_closed_without_configured_secret(client, monkeypatch):
    monkeypatch.delenv("HARNESS_RUNNER_TOKEN", raising=False)
    r = client.post("/run", json=VALID_BODY, headers={"Authorization": "Bearer anything"})
    assert r.status_code == 503  # unconfigured runner refuses to execute


def test_run_rejects_wrong_token(client, monkeypatch):
    monkeypatch.setenv("HARNESS_RUNNER_TOKEN", "the-real-secret")
    r = client.post("/run", json=VALID_BODY, headers={"Authorization": "Bearer wrong-secret"})
    assert r.status_code == 401


def test_authorize_rejects_non_ascii_token_without_typeerror(monkeypatch):
    """A non-ASCII bearer (an attacker can send latin-1 header bytes that
    Starlette decodes to a non-ASCII str) must fail closed via HTTPException(401),
    not raise TypeError inside hmac.compare_digest and surface as a 500 (Codex
    review). Tested at the _authorize level: the HTTP test client encodes headers
    as ASCII and would reject the value before it reaches the server."""
    from fastapi import HTTPException

    monkeypatch.setenv("HARNESS_RUNNER_TOKEN", "the-real-secret")
    with pytest.raises(HTTPException) as exc:
        runner_main._authorize("Bearer café-ÿ-™")
    assert exc.value.status_code == 401


def test_run_accepts_correct_token(client, monkeypatch):
    monkeypatch.setenv("HARNESS_RUNNER_TOKEN", "the-real-secret")
    # don't actually launch a sandbox — prove the correct token passes auth
    monkeypatch.setattr(
        runner_main,
        "run_inference",
        lambda **_kw: JobResult(ok=True, sandbox_mode="docker", raw={"ok": True}),
    )
    r = client.post(
        "/run", json=VALID_BODY, headers={"Authorization": "Bearer the-real-secret"}
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True
