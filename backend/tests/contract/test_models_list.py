"""GET /models — the oversight/history list surface.

Every submission the caller may read (object scope), each row carrying its latest
run's verdict + gated capability metric, and — the point of the endpoint — an
infra-failure reason when a run could not evaluate the model, so an un-loadable
submission is not silently 'pending' with no visible cause.
"""

from sqlmodel import Session

from app.db.enums import ModelClass, ModelStatus
from app.db.models import EvaluationRun, Model, ModelVersion
from app.db.repositories import get_engine
from tests.conftest import (
    HEALTHY_DET,
    bearer,
    det_manifest,
    register_golden,
    submit_model,
)


def test_models_list_requires_auth(client):
    r = client.get("/models", headers={"Authorization": "Bearer not-a-valid-token"})
    assert r.status_code == 401


def test_models_list_denies_role_without_read_scope(client):
    """A valid token lacking every read role (e.g. governance-only) is authorized
    with 403 — not silently handed an empty 200 — matching x-required-roles."""
    r = client.get("/models", headers=bearer("gov", ["governance"]))
    assert r.status_code == 403


def test_models_list_returns_submission_with_verdict_and_metric(client):
    register_golden(client, det_manifest())
    submit_model(client, weights_path=HEALTHY_DET, name="healthy-detector")

    r = client.get("/models")
    assert r.status_code == 200, r.text
    items = r.json()
    item = next(i for i in items if i["name"] == "healthy-detector")
    assert item["framework"] == "stub"
    assert item["model_class"] == "detection"
    # it was evaluated (not stuck pending/evaluating) — the exact terminal state
    # depends on the sample golden set, so assert it reached a decided status
    assert item["status"] in {"approved", "rejected", "pending_adjudication"}
    assert item["latest_verdict"] is not None
    assert item["infra_ok"] is True
    assert item["infra_error"] is None
    # the gated capability metric travels with the row
    assert item["headline_metric"] == "coco_ap_50_95"
    assert isinstance(item["headline_value"], float)


def test_models_list_surfaces_infra_failure_reason(client):
    """A run that could not load the model (infra_ok=false) leaves the version
    'pending'; the list must expose WHY, not just the bare status."""
    reason = "infra: failed to load pytorch weights: 'dict' object has no attribute 'eval'"
    with Session(get_engine()) as s:
        model = Model(name="broken-classifier", model_class=ModelClass.classification)
        s.add(model)
        s.flush()
        mv = ModelVersion(
            model_id=model.id,
            version="v1",
            artifact_ref="staged/broken.pt",
            framework="pytorch",
            status=ModelStatus.pending,
            submitted_by="harness-dev|someone",
        )
        s.add(mv)
        s.flush()
        s.add(EvaluationRun(model_version_id=mv.id, infra_ok=False, flag_trigger=reason))
        s.commit()

    r = client.get("/models")
    assert r.status_code == 200, r.text
    item = next(i for i in r.json() if i["name"] == "broken-classifier")
    assert item["status"] == "pending"
    assert item["infra_ok"] is False
    assert item["infra_error"] == reason
    assert item["latest_verdict"] is None
    assert item["headline_metric"] is None


def test_models_list_object_scope(client):
    """auditor sees all; a submitter sees only their own submissions."""
    register_golden(client, det_manifest())
    # submit as alice (submitter). submit_model uses the default all-roles header,
    # so override the Authorization for the upload to alice's submitter token.
    with open(HEALTHY_DET, "rb") as f:
        r = client.post(
            "/models",
            data={
                "name": "alice-model",
                "model_class": "detection",
                "framework": "stub",
                "version": "v1",
            },
            files={"weights": (HEALTHY_DET.name, f, "application/json")},
            headers=bearer("alice", ["submitter"]),
        )
    assert r.status_code == 201, r.text

    # bob (a different submitter) must NOT see alice's model
    r = client.get("/models", headers=bearer("bob", ["submitter"]))
    assert r.status_code == 200, r.text
    assert all(i["name"] != "alice-model" for i in r.json())

    # an auditor sees everything
    r = client.get("/models", headers=bearer("carol", ["auditor"]))
    assert r.status_code == 200, r.text
    assert any(i["name"] == "alice-model" for i in r.json())
