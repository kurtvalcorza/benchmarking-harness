"""Shared fixtures: isolated temp DB, inline eval mode, subprocess sandbox."""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
sys.path.insert(0, str(BACKEND))

SAMPLES = REPO / "samples"
DET_GOLDEN = SAMPLES / "golden" / "det-golden"
CLS_GOLDEN = SAMPLES / "golden" / "cls-golden"
SEG_GOLDEN = SAMPLES / "golden" / "seg-golden"
HEALTHY_DET = SAMPLES / "models" / "healthy_detector.stub.json"
WEAK_DET = SAMPLES / "models" / "weak_detector.stub.json"
HEALTHY_CLS = SAMPLES / "models" / "healthy_classifier.stub.json"
HEALTHY_SEG = SAMPLES / "models" / "healthy_segmenter.stub.json"


ALL_ROLES = ["submitter", "governance", "adjudicator", "auditor"]


def bearer(subject: str, roles: list[str]) -> dict[str, str]:
    """Auth header for a dev-signed token with the given subject/roles.

    Used by the role-matrix tests to exercise specific principals; the default
    `client` fixture attaches an all-roles token so pre-auth tests are unchanged.
    """
    from app.services.auth import mint_dev_token

    return {"Authorization": f"Bearer {mint_dev_token(subject, roles)}"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from app.db import repositories

    monkeypatch.setenv("HARNESS_DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    monkeypatch.setenv("HARNESS_EVAL_MODE", "inline")
    monkeypatch.setenv("HARNESS_SANDBOX_MODE", "subprocess")
    monkeypatch.setenv("HARNESS_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("HARNESS_RESULTS_DIR", str(tmp_path / "results"))
    monkeypatch.setenv("HARNESS_AUTH_MODE", "dev")
    # allowlist the committed samples, the data dir, and this test's tmp dir as
    # data roots so golden-set path containment (T020a) permits fixtures created
    # under tmp_path while still rejecting arbitrary host paths.
    monkeypatch.setenv(
        "HARNESS_DATA_ROOTS", f"{REPO / 'samples'},{REPO / 'data'},{tmp_path}"
    )
    repositories.reset_engine()

    from app.main import app

    with TestClient(app) as c:
        # authenticate every request by default with an all-roles dev principal;
        # role-matrix tests override the header per-request with `bearer(...)`.
        c.headers.update(bearer("dev-tester", ALL_ROLES))
        yield c
    repositories.reset_engine()


def det_manifest(**overrides) -> dict:
    m = {
        "name": "det-golden",
        "model_class": "detection",
        "version": "v1",
        "checksum": "auto",
        "conditions": ["rain", "low_light", "fog"],
        "safety_critical": ["pedestrian"],
        "recall_floors": {"pedestrian": 0.6},
        "license": "owned",
        "is_public": False,
        "domain": "local-context-demo",
        "data_ref": str(DET_GOLDEN),
    }
    m.update(overrides)
    return m


def cls_manifest(**overrides) -> dict:
    m = {
        "name": "cls-golden",
        "model_class": "classification",
        "version": "v1",
        "checksum": "auto",
        "conditions": ["rain", "low_light", "fog"],
        "safety_critical": ["animal"],
        "recall_floors": {"animal": 0.6},
        "license": "owned",
        "is_public": False,
        "domain": "local-context-demo",
        "data_ref": str(CLS_GOLDEN),
    }
    m.update(overrides)
    return m


def seg_manifest(**overrides) -> dict:
    m = {
        "name": "seg-golden",
        "model_class": "segmentation",
        "version": "v1",
        "checksum": "auto",
        "conditions": ["rain", "low_light", "fog"],
        "safety_critical": ["pedestrian"],
        # a segmentation set declares per-class IoU floors (FR-214); recall_floors
        # stays empty (segmentation reports IoU, not recall)
        "recall_floors": {},
        "iou_floors": {"pedestrian": 0.4},
        "license": "owned",
        "is_public": False,
        "domain": "local-context-demo",
        "data_ref": str(SEG_GOLDEN),
    }
    m.update(overrides)
    return m


def register_golden(client, manifest: dict) -> dict:
    r = client.post("/golden-sets", json=manifest)
    assert r.status_code == 201, r.text
    return r.json()


def submit_model(
    client,
    *,
    weights_path: Path,
    name: str,
    model_class: str = "detection",
    version: str = "v1",
    sources: list[str] | None = None,
) -> dict:
    data = {
        "name": name,
        "model_class": model_class,
        "framework": "stub",
        "version": version,
    }
    if sources is not None:
        data["declared_sources"] = sources
    with open(weights_path, "rb") as f:
        r = client.post(
            "/models",
            data=data,
            files={"weights": (weights_path.name, f, "application/json")},
        )
    assert r.status_code == 201, r.text
    return r.json()
