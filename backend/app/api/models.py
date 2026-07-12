"""Submitter surface: register/upload, status + card, history (T032/T033/T054)."""

import os
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.api.auth import (
    authorize_object_read,
    authorized_version_ids,
    get_principal,
    get_request_id,
    require_roles,
)
from app.api.schemas import (
    ArtifactReceiptOut,
    EvaluationRunOut,
    GoldenSetRef,
    ModelDetailOut,
    ModelListItemOut,
    ModelVersionOut,
)
from app.db.enums import JobReason, ModelClass, Role, Tier
from app.db.models import (
    ArtifactReceipt,
    EvaluationRun,
    Model,
    ModelCard,
    ModelVersion,
    TierResult,
)
from app.db.repositories import get_session
from app.services import audit, jobs, orchestrator
from app.services.artifact_ingest import (
    EmptyArtifact,
    StorageFull,
    UnsupportedArtifactType,
    UploadTooLarge,
    finalize,
    stage_upload,
)
from app.services.auth import Principal
from app.services.config import load_config
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
    except EmptyArtifact as e:
        raise HTTPException(422, str(e)) from None
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
    try:
        session.flush()
    except IntegrityError:
        # a concurrent submission won the (model_id, version) race at flush,
        # BEFORE our commit — discard the staged upload and return 409 rather
        # than 500-ing and leaking the .part file
        session.rollback()
        staged.discard()
        raise HTTPException(
            409, f"model '{name}' version '{version}' already exists"
        ) from None

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
    # US4 transactional outbox: create the durable evaluation intent IN THE SAME
    # transaction as the version + immutable receipt. A committed submission can
    # never lack its evaluation intent, so a queue outage no longer strands work
    # or 503s — the intent is durable and the dispatcher reclaims a lost publish.
    intent = jobs.create_intent(
        session, model_version_id=mv.id, reason=JobReason.submission
    )
    intent_id = intent.id
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

    # FR-003: auto-trigger, no manual step. Best-effort publish — a broker outage
    # here leaves the durable pending intent for the dispatcher to reclaim, so the
    # submission still succeeds (201) rather than 503-ing on a recoverable gap.
    try:
        orchestrator.dispatch_intent(intent_id, mv.id)
    except Exception:  # noqa: BLE001 — durable intent guarantees eventual dispatch
        pass
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
        submitted_by=mv.submitted_by,
        artifact=ArtifactReceiptOut(
            id=receipt.id,
            sha256=receipt.sha256,
            byte_count=receipt.byte_count,
            original_filename=receipt.original_filename,
            finalized_at=receipt.finalized_at,
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


@router.get("/models", response_model=list[ModelListItemOut])
def list_models(
    session: Session = Depends(get_session),
    principal: Principal = Depends(get_principal),
) -> list[ModelListItemOut]:
    """Oversight/history list of the submissions the caller may read (object
    scope, security-boundary.md): auditor→all, submitter→own, adjudicator→flagged
    (governance holds no arbitrary model read). Each row summarizes the version's
    latest run — verdict, the gated capability metric, and an infra-failure reason
    when a run could not evaluate the model — so a submission that failed to load
    is not silently 'pending' with no visible cause. Newest submission first.
    """
    versions = list(session.exec(select(ModelVersion)).all())
    allowed = set(authorized_version_ids(principal, versions, session))
    versions = [v for v in versions if v.id in allowed]
    if not versions:
        return []

    models = {m.id: m for m in session.exec(select(Model)).all()}
    version_ids = [v.id for v in versions]

    latest_run: dict[str, EvaluationRun] = {}
    for r in session.exec(
        select(EvaluationRun).where(EvaluationRun.model_version_id.in_(version_ids))  # type: ignore[attr-defined]
    ).all():
        prev = latest_run.get(r.model_version_id)
        if prev is None or r.started_at > prev.started_at:
            latest_run[r.model_version_id] = r

    capability: dict[str, TierResult] = {}
    run_ids = [r.id for r in latest_run.values()]
    if run_ids:
        for tr in session.exec(
            select(TierResult).where(
                TierResult.run_id.in_(run_ids),  # type: ignore[attr-defined]
                TierResult.tier == Tier.capability,
            )
        ).all():
            capability.setdefault(tr.run_id, tr)

    items: list[ModelListItemOut] = []
    for v in versions:
        model = models[v.model_id]
        run = latest_run.get(v.id)
        metric = value = None
        infra_error = None
        if run is not None:
            if not run.infra_ok:
                # the load/sandbox failure that left the model un-evaluated (FR-012)
                infra_error = run.flag_trigger
            cap = capability.get(run.id)
            if cap and cap.threshold:
                metric = cap.threshold.get("metric")
                raw = cap.metrics.get(metric) if (metric and cap.metrics) else None
                value = float(raw) if isinstance(raw, (int, float)) else None
        items.append(
            ModelListItemOut(
                id=v.id,
                model_id=v.model_id,
                name=model.name,
                model_class=model.model_class,
                version=v.version,
                framework=v.framework,
                status=v.status,
                submitted_at=v.submitted_at,
                submitted_by=v.submitted_by,
                latest_verdict=run.verdict if run else None,
                evaluated_at=run.finished_at if run else None,
                infra_ok=run.infra_ok if run else True,
                infra_error=infra_error,
                headline_metric=metric,
                headline_value=value,
            )
        )
    items.sort(key=lambda i: i.submitted_at, reverse=True)
    return items


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
        submitted_by=mv.submitted_by,
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
    """FR-016: append-only performance history across the versions the caller is
    authorized for, in order."""
    mv = _resolve_version(session, id)
    authorize_object_read(principal, mv, session)
    versions = session.exec(
        select(ModelVersion).where(ModelVersion.model_id == mv.model_id)
    ).all()
    # object scope: two submitters can share a model name/class, so history must
    # not leak sibling versions the caller does not own / is not related to
    version_ids = authorized_version_ids(principal, versions, session)
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
