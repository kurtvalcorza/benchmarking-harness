"""Submitter surface: register/upload, status + card, history (T032/T033/T054)."""

import os
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.api.schemas import (
    EvaluationRunOut,
    GoldenSetRef,
    ModelDetailOut,
    ModelVersionOut,
)
from app.db.enums import ModelClass
from app.db.models import EvaluationRun, Model, ModelCard, ModelVersion
from app.db.repositories import get_session
from app.services import audit
from app.services.orchestrator import enqueue_evaluation
from engine.adapters.base import SUPPORTED_FRAMEWORKS
from engine.datasets import REPO_ROOT
from engine.metrics import SCORED_CLASSES
from engine.registry.registry import REGISTRY

router = APIRouter(tags=["models"])


def artifacts_dir() -> Path:
    return Path(os.environ.get("HARNESS_ARTIFACTS_DIR", REPO_ROOT / "data" / "artifacts"))


@router.post("/models", status_code=201, response_model=ModelVersionOut)
async def submit_model(
    weights: UploadFile,
    name: str = Form(...),
    model_class: str = Form(...),
    framework: str = Form(...),
    version: str = Form("v1"),
    declared_sources: list[str] = Form(default=[]),
    session: Session = Depends(get_session),
) -> ModelVersionOut:
    try:
        mc = ModelClass(model_class)
    except ValueError:
        raise HTTPException(422, f"unknown model_class '{model_class}'") from None
    if mc not in REGISTRY:
        raise HTTPException(422, f"no benchmark registered for class '{mc.value}' (FR-006)")
    if mc not in SCORED_CLASSES:
        # registered slot, scorer not yet implemented (FR-025): refuse up front
        # with a clear message instead of failing mid-evaluation as infra
        raise HTTPException(
            422,
            f"model class '{mc.value}' is registered but its scorer is not implemented in "
            f"the POC — supported end-to-end: {sorted(c.value for c in SCORED_CLASSES)}",
        )
    if framework.lower() not in SUPPORTED_FRAMEWORKS:
        raise HTTPException(
            422, f"unsupported framework '{framework}' (supported: {SUPPORTED_FRAMEWORKS})"
        )

    model = session.exec(
        select(Model).where(Model.name == name, Model.model_class == mc)
    ).first()
    if model is None:
        model = Model(name=name, model_class=mc)
        session.add(model)
        session.flush()
    existing = session.exec(
        select(ModelVersion).where(
            ModelVersion.model_id == model.id, ModelVersion.version == version
        )
    ).first()
    if existing:
        raise HTTPException(422, f"version '{version}' already exists for model '{name}'")

    mv = ModelVersion(
        model_id=model.id,
        version=version,
        artifact_ref="",  # set below once the id exists
        framework=framework.lower(),
        declared_sources=[s for s in declared_sources if s and s.strip()],
    )
    session.add(mv)
    session.flush()

    dest = (artifacts_dir() / mv.id).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    # the filename is client-controlled: strip any path components so an
    # upload named "../../x" can never escape the version's artifact dir
    safe_name = Path(weights.filename or "").name or "weights.bin"
    artifact_path = (dest / safe_name).resolve()
    if not artifact_path.is_relative_to(dest):
        raise HTTPException(422, "invalid weights filename")
    # stream to disk: real .pt/.onnx artifacts are large — never buffer the
    # whole payload in API memory
    with artifact_path.open("wb") as f:
        shutil.copyfileobj(weights.file, f, length=1024 * 1024)
    mv.artifact_ref = str(artifact_path)
    session.add(mv)
    audit.record(
        session,
        actor="submitter",
        action="model-version-submitted",
        target_ref=f"model_version:{mv.id}",
    )
    try:
        session.commit()
    except IntegrityError:
        # concurrent duplicate submission lost the race on a uniqueness
        # constraint — (model_id, version) or the Model's (name, model_class)
        session.rollback()
        shutil.rmtree(dest, ignore_errors=True)
        raise HTTPException(
            422,
            f"model '{name}' version '{version}' already exists (or was submitted "
            "concurrently) — resubmit with a new version",
        ) from None
    session.refresh(mv)

    try:
        enqueue_evaluation(mv.id)  # FR-003: auto-trigger, no manual step
    except Exception as e:
        # nothing ran yet → roll the submission back so a retry with the same
        # name/version doesn't trip the duplicate check while no job exists
        has_runs = session.exec(
            select(EvaluationRun).where(EvaluationRun.model_version_id == mv.id)
        ).first()
        if has_runs is None:
            session.delete(mv)
            session.commit()
            shutil.rmtree(dest, ignore_errors=True)
            raise HTTPException(
                503, f"evaluation queue unavailable; submission rolled back — retry ({e})"
            ) from e
        raise
    session.refresh(mv)
    return _version_out(session, mv)


def _version_out(session: Session, mv: ModelVersion) -> ModelVersionOut:
    model = session.get(Model, mv.model_id)
    return ModelVersionOut(
        id=mv.id,
        model_id=mv.model_id,
        name=model.name,
        model_class=model.model_class,
        version=mv.version,
        framework=mv.framework,
        status=mv.status,
        submitted_at=mv.submitted_at,
    )


def _resolve_version(session: Session, id_: str) -> ModelVersion:
    mv = session.get(ModelVersion, id_)
    if mv:
        return mv
    model = session.get(Model, id_)
    if model:
        versions = session.exec(
            select(ModelVersion).where(ModelVersion.model_id == model.id)
        ).all()
        if versions:
            return max(versions, key=lambda v: v.submitted_at)
    raise HTTPException(404, "model not found")


@router.get("/models/{id}", response_model=ModelDetailOut)
def get_model(id: str, session: Session = Depends(get_session)) -> ModelDetailOut:
    mv = _resolve_version(session, id)
    model = session.get(Model, mv.model_id)
    card = session.exec(
        select(ModelCard).where(ModelCard.model_version_id == mv.id)
    ).first()
    return ModelDetailOut(
        id=mv.id,
        model_id=mv.model_id,
        name=model.name,
        model_class=model.model_class,
        version=mv.version,
        framework=mv.framework,
        status=mv.status,
        submitted_at=mv.submitted_at,
        declared_sources=list(mv.declared_sources or []),
        card_markdown=(card.human_sections + card.machine_blocks) if card else None,
        missing_card_fields=list(card.missing_fields or []) if card else [],
    )


@router.get("/models/{id}/history", response_model=list[EvaluationRunOut])
def get_history(id: str, session: Session = Depends(get_session)) -> list[EvaluationRunOut]:
    """FR-016: append-only performance history across ALL versions, in order."""
    mv = _resolve_version(session, id)
    versions = session.exec(
        select(ModelVersion).where(ModelVersion.model_id == mv.model_id)
    ).all()
    version_ids = [v.id for v in versions]
    runs = session.exec(
        select(EvaluationRun)
        .where(EvaluationRun.model_version_id.in_(version_ids))  # type: ignore[attr-defined]
        .order_by(EvaluationRun.started_at)
    ).all()
    return [
        EvaluationRunOut(
            id=r.id,
            model_version_id=r.model_version_id,
            verdict=r.verdict,
            golden_set=GoldenSetRef(
                id=r.golden_set_id, version=r.golden_set_version, checksum=r.golden_set_checksum
            ),
            started_at=r.started_at,
            finished_at=r.finished_at,
            infra_ok=r.infra_ok,
            flag_trigger=r.flag_trigger,
        )
        for r in runs
    ]
