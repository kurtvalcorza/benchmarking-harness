"""Submitter surface: register/upload, status + card, history (T032/T033/T054)."""

import os
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.api.auth import authorize_object_read, get_principal, get_request_id, require_roles
from app.api.schemas import (
    ArtifactReceiptOut,
    EvaluationRunOut,
    GoldenSetRef,
    ModelDetailOut,
    ModelVersionOut,
)
from app.db.enums import ModelClass, Role
from app.db.models import ArtifactReceipt, EvaluationRun, Model, ModelCard, ModelVersion
from app.db.repositories import get_session
from app.services import audit
from app.services.artifact_ingest import (
    StorageFull,
    UnsupportedArtifactType,
    UploadTooLarge,
    finalize,
    stage_upload,
)
from app.services.auth import Principal
from app.services.config import load_config
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
    principal: Principal = Depends(require_roles(Role.submitter)),
    request_id: str = Depends(get_request_id),
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
        # duplicate version is a conflict, not a malformed request (openapi 409)
        raise HTTPException(409, f"version '{version}' already exists for model '{name}'")

    # US3: stream the upload to a bounded, hashed `.part` BEFORE creating any
    # domain state — memory stays O(chunk) and an oversized/interrupted upload
    # never leaves a partial artifact.
    cfg = load_config()
    try:
        staged = stage_upload(weights.file, weights.filename, framework, cfg)
    except UploadTooLarge as e:
        raise HTTPException(413, str(e)) from None
    except UnsupportedArtifactType as e:
        raise HTTPException(415, str(e)) from None
    except StorageFull as e:
        raise HTTPException(507, str(e)) from None

    mv = ModelVersion(
        model_id=model.id,
        version=version,
        artifact_ref="",  # set below, after the artifact is finalized
        framework=framework.lower(),
        declared_sources=[s for s in declared_sources if s and s.strip()],
        submitted_by=principal.principal_key,  # FR-001: verified identity
    )
    session.add(mv)
    session.flush()

    dest_dir = artifacts_dir() / mv.id
    final_ref = str(dest_dir / staged.original_filename)
    receipt = ArtifactReceipt(
        storage_ref=final_ref,
        original_filename=staged.original_filename,
        byte_count=staged.byte_count,
        sha256=staged.sha256,
        framework=framework.lower(),
        submitted_by=principal.principal_key,
    )
    session.add(receipt)
    mv.artifact_receipt_id = receipt.id

    try:
        final_path = finalize(staged, dest_dir)  # atomic move into place
    except StorageFull as e:
        session.rollback()
        staged.discard()
        raise HTTPException(507, str(e)) from None
    mv.artifact_ref = str(final_path)
    receipt.storage_ref = str(final_path)
    session.add(mv)
    session.add(receipt)
    audit.record(
        session,
        actor=principal.principal_key,
        action="model-version-submitted",
        target_ref=f"model_version:{mv.id}",
        request_id=request_id,
        principal_issuer=principal.issuer,
        outcome="success",
        metadata={"sha256": staged.sha256, "byte_count": staged.byte_count},
    )
    try:
        session.commit()
    except IntegrityError:
        # concurrent duplicate submission lost the race on a uniqueness
        # constraint — (model_id, version) or the Model's (name, model_class)
        session.rollback()
        staged.discard()
        shutil.rmtree(dest_dir, ignore_errors=True)
        raise HTTPException(
            409,
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
            shutil.rmtree(dest_dir, ignore_errors=True)
            raise HTTPException(
                503, f"evaluation queue unavailable; submission rolled back — retry ({e})"
            ) from e
        raise
    session.refresh(mv)
    return _version_out(session, mv)


def _version_out(session: Session, mv: ModelVersion) -> ModelVersionOut:
    model = session.get(Model, mv.model_id)
    receipt = (
        session.get(ArtifactReceipt, mv.artifact_receipt_id)
        if mv.artifact_receipt_id
        else None
    )
    return ModelVersionOut(
        id=mv.id,
        model_id=mv.model_id,
        name=model.name,
        model_class=model.model_class,
        version=mv.version,
        framework=mv.framework,
        status=mv.status,
        submitted_at=mv.submitted_at,
        artifact=ArtifactReceiptOut(
            id=receipt.id,
            sha256=receipt.sha256,
            byte_count=receipt.byte_count,
            original_filename=receipt.original_filename,
        )
        if receipt
        else None,
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
def get_model(
    id: str,
    session: Session = Depends(get_session),
    principal: Principal = Depends(get_principal),
) -> ModelDetailOut:
    mv = _resolve_version(session, id)
    authorize_object_read(principal, mv, session)
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
def get_history(
    id: str,
    session: Session = Depends(get_session),
    principal: Principal = Depends(get_principal),
) -> list[EvaluationRunOut]:
    """FR-016: append-only performance history across ALL versions, in order."""
    mv = _resolve_version(session, id)
    authorize_object_read(principal, mv, session)
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
