"""Adjudication surface (T040/T041, FR-012/013, Constitution I).

POST /adjudication/{runId}/decision is the ONLY path that can move a flagged
model to `approved` — there is no force-approve endpoint anywhere in the API,
and the state machine rejects any other route (tested by
tests/contract/test_no_auto_approval.py).
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.api.schemas import AdjudicationItemOut, DecisionIn
from app.db.enums import Decision, ModelStatus, Tier, Verdict
from app.db.models import (
    AdjudicationRecord,
    EvaluationRun,
    Model,
    ModelVersion,
    TierResult,
)
from app.db.repositories import get_session
from app.services import audit
from app.services.orchestrator import _regenerate_card
from app.services.state_machine import apply_adjudication

router = APIRouter(tags=["adjudication"])


@router.get("/adjudication/queue", response_model=list[AdjudicationItemOut])
def queue(session: Session = Depends(get_session)) -> list[AdjudicationItemOut]:
    runs = session.exec(
        select(EvaluationRun).where(EvaluationRun.verdict == Verdict.pending_adjudication)
    ).all()
    items: list[AdjudicationItemOut] = []
    for run in runs:
        version = session.get(ModelVersion, run.model_version_id)
        if version is None or version.status is not ModelStatus.pending_adjudication:
            continue  # already decided
        tiers = session.exec(select(TierResult).where(TierResult.run_id == run.id)).all()
        evidence = "; ".join(t.evidence_ref for t in tiers if t.evidence_ref)
        model = session.get(Model, version.model_id)
        items.append(
            AdjudicationItemOut(
                run_id=run.id,
                trigger=run.flag_trigger,
                evidence_ref=evidence,
                model_version_id=version.id,
                model_name=model.name if model else None,
                flagged_at=run.finished_at,
            )
        )
    return items


@router.post("/adjudication/{run_id}/decision")
def decide(
    run_id: str, body: DecisionIn, session: Session = Depends(get_session)
) -> dict:
    run = session.get(EvaluationRun, run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    version = session.get(ModelVersion, run.model_version_id)
    if (
        run.verdict is not Verdict.pending_adjudication
        or version.status is not ModelStatus.pending_adjudication
    ):
        raise HTTPException(409, "run is not pending adjudication")

    if body.decision is Decision.approve:
        # data-model validation rule: `approved` requires a stored TierResult
        # for EVERY tier. A halted run (e.g. Tier 1 failed + provenance flag)
        # lacks the operational-safety lineage and cannot be approved.
        tiers_present = {
            t.tier for t in session.exec(select(TierResult).where(TierResult.run_id == run.id))
        }
        missing = [t.value for t in Tier if t not in tiers_present]
        if missing:
            raise HTTPException(
                409,
                f"cannot approve: run lacks results for tiers {missing} — the full "
                "three-tier lineage is required for approval (reject or request changes)",
            )

    record = AdjudicationRecord(
        run_id=run.id,
        trigger=run.flag_trigger or "flagged",
        evidence_ref="; ".join(
            t.evidence_ref
            for t in session.exec(select(TierResult).where(TierResult.run_id == run.id)).all()
        ),
        reviewer=body.reviewer,
        decision=body.decision,
        rationale=body.rationale,
    )
    session.add(record)  # the decision is recorded IN THE SAME transaction (FR-013)

    version.status = apply_adjudication(version.status, body.decision)
    session.add(version)
    audit.record(
        session,
        actor=body.reviewer,
        action=f"adjudication:{body.decision.value}",
        target_ref=f"run:{run.id}",
    )
    session.commit()

    model = session.get(Model, version.model_id)
    _regenerate_card(session, version.id, model.name, sandbox_mode=None)
    session.commit()
    return {
        "run_id": run.id,
        "decision": body.decision.value,
        "model_version_id": version.id,
        "status": version.status.value,
    }
