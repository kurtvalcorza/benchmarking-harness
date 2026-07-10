"""T022 — POST /models contract + auto-trigger (FR-001/002/003)."""

from tests.conftest import (
    HEALTHY_DET,
    WEAK_DET,
    det_manifest,
    register_golden,
    submit_model,
)


def test_submit_returns_201_with_identity_and_pending_start(client):
    register_golden(client, det_manifest())
    body = submit_model(
        client, weights_path=HEALTHY_DET, name="api-contract", sources=["synthetic v1"]
    )
    assert body["id"]
    assert body["model_class"] == "detection"
    assert body["framework"] == "stub"
    assert body["version"] == "v1"
    # FR-003: evaluation auto-triggered — inline mode has already finished it
    assert body["status"] in ("approved", "rejected", "pending_adjudication", "evaluating")


def test_auto_trigger_creates_a_run_without_manual_step(client):
    register_golden(client, det_manifest())
    body = submit_model(client, weights_path=HEALTHY_DET, name="auto-run", sources=["s"])
    history = client.get(f"/models/{body['id']}/history").json()
    assert len(history) == 1  # a run exists although we never called a "run" endpoint


def test_unknown_model_class_is_422(client):
    with open(HEALTHY_DET, "rb") as f:
        r = client.post(
            "/models",
            data={"name": "x", "model_class": "hologram", "framework": "stub"},
            files={"weights": ("w.json", f)},
        )
    assert r.status_code == 422


def test_unknown_framework_is_422(client):
    with open(HEALTHY_DET, "rb") as f:
        r = client.post(
            "/models",
            data={"name": "x", "model_class": "detection", "framework": "matlab"},
            files={"weights": ("w.json", f)},
        )
    assert r.status_code == 422


def test_duplicate_version_is_422(client):
    register_golden(client, det_manifest())
    submit_model(client, weights_path=HEALTHY_DET, name="dup", sources=["s"])
    with open(WEAK_DET, "rb") as f:
        r = client.post(
            "/models",
            data={"name": "dup", "model_class": "detection", "framework": "stub", "version": "v1"},
            files={"weights": ("w.json", f)},
        )
    assert r.status_code == 422


def test_missing_provenance_is_captured_and_flagged_not_rejected_at_submit(client):
    """FR-002: missing provenance flags the run (FR-012c), never blocks upload."""
    register_golden(client, det_manifest())
    body = submit_model(client, weights_path=HEALTHY_DET, name="no-prov")  # no sources
    assert body["status"] == "pending_adjudication"
    detail = client.get(f"/models/{body['id']}").json()
    assert detail["declared_sources"] == []


def test_get_unknown_model_404(client):
    assert client.get("/models/nope").status_code == 404
