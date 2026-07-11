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
HEALTHY_DET = SAMPLES / "models" / "healthy_detector.stub.json"
WEAK_DET = SAMPLES / "models" / "weak_detector.stub.json"
HEALTHY_CLS = SAMPLES / "models" / "healthy_classifier.stub.json"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from app.db import repositories

    monkeypatch.setenv("HARNESS_DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    monkeypatch.setenv("HARNESS_EVAL_MODE", "inline")
    monkeypatch.setenv("HARNESS_SANDBOX_MODE", "subprocess")
    monkeypatch.setenv("HARNESS_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("HARNESS_RESULTS_DIR", str(tmp_path / "results"))
    repositories.reset_engine()

    from app.main import app

    with TestClient(app) as c:
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
