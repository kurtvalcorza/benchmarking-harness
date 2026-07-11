"""Run detail: why a model passed/failed, per tier (T033, SC-009)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.api.auth import authorize_run_read, require_roles
from app.api.schemas import GoldenSetRef, RunDetailOut, TierResultOut
from app.db.enums import Role
from app.db.models import EvaluationRun, TierResult
from app.db.repositories import get_session
from app.services.auth import Principal

router = APIRouter(tags=["runs"])


@router.get("/runs/{run_id}", response_model=RunDetailOut)
def get_run(
    run_id: str,
    session: Session = Depends(get_session),
    principal: Principal = Depends(
        require_roles(Role.submitter, Role.governance, Role.adjudicator, Role.auditor)
    ),
) -> RunDetailOut:
    run = session.get(EvaluationRun, run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    # role gate passed; now enforce the per-run object scope (a governance or
    # adjudicator token may only read runs it is related to)
    authorize_run_read(principal, run, session)
    tiers = session.exec(
        select(TierResult).where(TierResult.run_id == run_id)
    ).all()
    return RunDetailOut(
        id=run.id,
        model_version_id=run.model_version_id,
        verdict=run.verdict,
        golden_set=GoldenSetRef(
            id=run.golden_set_id,
            version=run.golden_set_version,
            checksum=run.golden_set_checksum,
        ),
        started_at=run.started_at,
        finished_at=run.finished_at,
        infra_ok=run.infra_ok,
        flag_trigger=run.flag_trigger,
        tier_results=[
            TierResultOut(
                tier=t.tier,
                condition=t.condition,
                metrics=t.metrics,
                threshold=t.threshold,
                passed=t.passed,
                evidence_ref=t.evidence_ref,
                dataset_checksum=t.dataset_checksum,
                coverage=t.coverage,
                evaluator=t.evaluator,
                evidence_digest=t.evidence_digest,
            )
            for t in tiers
        ],
    )
