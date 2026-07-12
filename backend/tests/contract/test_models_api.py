"""T022 — POST /models contract + auto-trigger (FR-001/002/003)."""

from tests.conftest import (
    HEALTHY_DET,
    WEAK_DET,
    det_manifest,
    register_golden,
    seg_manifest,
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


def test_unsupported_framework_class_pair_is_422_not_stored(client):
    """segmentation+onnx is a supported framework and a scored class, but the
    ONNX adapter has no segmentation runner — the submit guard must refuse it up
    front (clear 422) instead of storing the version and infra-failing at load."""
    with open(HEALTHY_DET, "rb") as f:
        r = client.post(
            "/models",
            data={"name": "seg-onnx", "model_class": "segmentation", "framework": "onnx"},
            files={"weights": ("w.json", f)},
        )
    assert r.status_code == 422, r.text
    assert "segmentation" in r.text


def test_unknown_framework_is_422(client):
    with open(HEALTHY_DET, "rb") as f:
        r = client.post(
            "/models",
            data={"name": "x", "model_class": "detection", "framework": "matlab"},
            files={"weights": ("w.json", f)},
        )
    assert r.status_code == 422


def test_duplicate_version_is_409(client):
    register_golden(client, det_manifest())
    submit_model(client, weights_path=HEALTHY_DET, name="dup", sources=["s"])
    with open(WEAK_DET, "rb") as f:
        r = client.post(
            "/models",
            data={"name": "dup", "model_class": "detection", "framework": "stub", "version": "v1"},
            files={"weights": ("w.json", f)},
        )
    assert r.status_code == 409  # duplicate version is a conflict (openapi 002)


def test_missing_provenance_is_captured_and_flagged_not_rejected_at_submit(client):
    """FR-002: missing provenance flags the run (FR-012c), never blocks upload."""
    register_golden(client, det_manifest())
    body = submit_model(client, weights_path=HEALTHY_DET, name="no-prov")  # no sources
    assert body["status"] == "pending_adjudication"
    detail = client.get(f"/models/{body['id']}").json()
    assert detail["declared_sources"] == []


def test_get_unknown_model_404(client):
    assert client.get("/models/nope").status_code == 404


def test_upload_filename_cannot_escape_artifact_dir(client, tmp_path):
    """A weights filename with path components must be stored INSIDE the
    version's artifact dir — never resolved against the parent tree."""
    import os

    register_golden(client, det_manifest())
    with open(HEALTHY_DET, "rb") as f:
        r = client.post(
            "/models",
            data={
                "name": "traversal",
                "model_class": "detection",
                "framework": "stub",
                "declared_sources": ["s"],
            },
            files={"weights": ("../../evil.json", f, "application/json")},
        )
    assert r.status_code == 201, r.text
    artifacts_root = os.environ["HARNESS_ARTIFACTS_DIR"]
    # nothing escaped above the artifacts root
    assert not (tmp_path / "evil.json").exists()
    escaped = [
        p
        for p in tmp_path.rglob("evil.json")
        if not str(p).startswith(artifacts_root)
    ]
    assert escaped == [], f"upload escaped the artifact dir: {escaped}"


def test_scorerless_registered_class_is_422_up_front(client):
    """Registered classes without a POC scorer (e.g. pose — detection,
    classification and segmentation are all scored now) are refused at submission
    with a clear message, not mid-run as an infra failure (FR-025)."""
    with open(HEALTHY_DET, "rb") as f:
        r = client.post(
            "/models",
            data={"name": "pose", "model_class": "pose", "framework": "stub"},
            files={"weights": ("w.json", f)},
        )
    assert r.status_code == 422
    assert "scorer" in r.text


def test_segmentation_golden_set_accepts_recall_floors_as_iou_fallback(client):
    """The published golden-set contract exposes `recall_floors`; a segmentation
    set that declares its floors there (and omits `iou_floors`) must register,
    not be rejected with a missing-floor 422."""
    m = seg_manifest(
        name="seg-golden-recall-fallback",
        iou_floors={},
        recall_floors={"pedestrian": 0.4},
    )
    r = client.post("/golden-sets", json=m)
    assert r.status_code == 201, r.text
