"""Evaluation orchestrator (T031/T034/T059).

Runs the three tiers IN ORDER, halts on a hard tier failure (FR-007), persists
the run + per-tier results append-only in one transaction, applies the FR-012
flag rule, transitions ModelVersion.status, and (re)generates the Model Card.

All inference is dispatched through the no-egress sandbox runner (D1) — this
process never loads model weights.

Execution modes:
- HARNESS_EVAL_MODE=rq (default): enqueue on Redis/RQ; worker/main.py consumes.
- HARNESS_EVAL_MODE=inline: run synchronously in-process (tests, offline demo).
"""

import json
import os
from pathlib import Path

from sqlmodel import Session, select

from app.db.enums import Condition, ModelClass, ModelStatus, Tier
from app.db.models import (
    AdjudicationRecord,
    EvaluationRun,
    GoldenTestSet,
    Model,
    ModelCard,
    ModelVersion,
    TierResult,
    utcnow,
)
from app.db.repositories import get_engine
from app.services import audit
from app.services.config import get_threshold
from app.services.state_machine import assert_transition, status_for_verdict
from engine.cards import generator as cards
from engine.datasets import REPO_ROOT, Dataset
from engine.sandbox.runner import SandboxError
from engine.scoring import score_run
from engine.tiers.tier1_capability import TierOutcome, run_tier1
from engine.tiers.tier2_stress import run_tier2
from engine.tiers.tier3_ops import run_tier3

HARNESS_VERSION = "0.1.0"


def results_dir() -> Path:
    return Path(os.environ.get("HARNESS_RESULTS_DIR", REPO_ROOT / "data" / "results"))


def eval_mode() -> str:
    return os.environ.get("HARNESS_EVAL_MODE", "rq")


def enqueue_evaluation(version_id: str) -> None:
    """FR-003: evaluation starts automatically on upload — no manual trigger."""
    if eval_mode() == "inline":
        evaluate_version(version_id)
        return
    from redis import Redis
    from rq import Queue

    q = Queue("evaluations", connection=Redis.from_url(
        os.environ.get("HARNESS_REDIS_URL", "redis://localhost:6379/0")
    ))
    q.enqueue("app.services.orchestrator.evaluate_version", version_id, job_timeout=7200)


def _latest_golden_set(session: Session, model_class: ModelClass) -> GoldenTestSet | None:
    sets = session.exec(
        select(GoldenTestSet).where(GoldenTestSet.model_class == model_class)
    ).all()
    return max(sets, key=lambda s: s.registered_at) if sets else None


def evaluate_version(version_id: str) -> str | None:
    """Run the full three-tier evaluation for a ModelVersion. Returns run id."""
    with Session(get_engine()) as session:
        version = session.get(ModelVersion, version_id)
        if version is None:
            raise ValueError(f"unknown model version {version_id}")
        model = session.get(Model, version.model_id)
        assert_transition(version.status, ModelStatus.evaluating)
        version.status = ModelStatus.evaluating
        audit.record(
            session,
            actor="orchestrator",
            action="status-change:evaluating",
            target_ref=f"model_version:{version.id}",
        )
        session.add(version)
        session.commit()
        session.refresh(version)
        golden = _latest_golden_set(session, model.model_class)
        model_class = model.model_class
        framework, artifact = version.framework, version.artifact_ref
        declared_sources = list(version.declared_sources or [])
        model_name = model.name

    run = EvaluationRun(
        model_version_id=version_id,
        harness_version=HARNESS_VERSION,
        golden_set_id=golden.id if golden else None,
        golden_set_version=golden.version if golden else None,
        golden_set_checksum=golden.checksum if golden else None,
        started_at=utcnow(),
    )
    outcomes: list[TierOutcome] = []
    safety_breach = False
    infra_error: str | None = None
    sandbox_mode_used: str | None = None

    try:
        # ---- Tier 1: capability (registry-selected benchmark) ----
        t1 = run_tier1(
            framework=framework,
            artifact=artifact,
            model_class=model_class,
            threshold=get_threshold(model_class, Tier.capability),
        )
        outcomes.append(t1)
        sandbox_mode_used = t1.evidence.get("sandbox_mode")
        if t1.adapter_error:
            infra_error = t1.adapter_error
        elif t1.passed is False:
            pass  # FR-007: halt — Tier 2/3 skipped, failing scores still recorded
        else:
            # ---- Tier 2: domain stress on the Golden Test Set ----
            if golden is None:
                infra_error = (
                    f"no golden test set registered for class '{model_class.value}' "
                    "(register one via POST /golden-sets)"
                )
            elif Dataset(root=Path(golden.data_ref)).checksum() != golden.checksum:
                # contamination guard (FR-018, Constitution IV): the data on
                # disk drifted from what governance registered — never score
                # against it and never stamp results with a stale checksum
                infra_error = (
                    f"golden set '{golden.id}' content no longer matches its registered "
                    "checksum — refusing to evaluate against drifted data (re-register)"
                )
            else:
                t2 = run_tier2(
                    framework=framework,
                    artifact=artifact,
                    model_class=model_class,
                    golden_root=golden.data_ref,
                    conditions=[Condition(c) for c in golden.conditions],
                    safety_classes=list(golden.safety_critical_classes or []),
                    recall_floors=dict(golden.recall_floors or {}),
                    threshold=get_threshold(model_class, Tier.domain_stress),
                )
                if t2.adapter_error:
                    infra_error = t2.adapter_error
                else:
                    outcomes.extend(t2.outcomes)
                    safety_breach = t2.safety_breach
                    # FR-007: any condition below its RATIFIED threshold halts
                    # progression, even when another condition independently
                    # raised an unratified/safety flag — the flags still route
                    # the final verdict to adjudication via score_run.
                    hard_fail = t2.passed is False
                    if not hard_fail:
                        # ---- Tier 3: interpretability + resource profile ----
                        t3 = run_tier3(
                            framework=framework,
                            artifact=artifact,
                            model_class=model_class,
                            threshold=get_threshold(model_class, Tier.operational_safety),
                        )
                        outcomes.append(t3)
                        if t3.adapter_error:
                            infra_error = t3.adapter_error
    except (SandboxError, NotImplementedError, FileNotFoundError) as e:
        infra_error = str(e)
    except Exception as e:  # noqa: BLE001 — any unexpected crash is an infra
        # failure: record it and return the version to `pending` rather than
        # dying mid-`evaluating` with no append-only run (worker robustness)
        infra_error = f"unexpected {type(e).__name__}: {e}"

    run.finished_at = utcnow()

    with Session(get_engine()) as session:
        version = session.get(ModelVersion, version_id)
        if infra_error:
            # infra failure ≠ model failure (spec edge case): no model verdict
            run.infra_ok = False
            run.verdict = None
            run.flag_trigger = f"infra:{infra_error[:300]}"
            session.add(run)
            _persist_tier_results(session, run, outcomes, golden)
            version.status = ModelStatus.pending  # eligible for retry/resubmission
            audit.record(
                session,
                actor="orchestrator",
                action="run-infra-failure",
                target_ref=f"run:{run.id}",
            )
            session.add(version)
            session.commit()
            return run.id

        score = score_run(
            outcomes=outcomes,
            safety_breach=safety_breach,
            declared_sources=declared_sources,
        )
        run.verdict = score.verdict
        run.flag_trigger = score.flag_trigger
        session.add(run)
        _persist_tier_results(session, run, outcomes, golden)

        new_status = status_for_verdict(score.verdict)
        assert_transition(version.status, new_status)
        version.status = new_status
        session.add(version)
        audit.record(
            session,
            actor="orchestrator",
            action=f"status-change:{new_status.value}",
            target_ref=f"model_version:{version.id}",
            checksum=golden.checksum if golden else None,
        )
        session.commit()

        _regenerate_card(session, version_id, model_name, sandbox_mode_used)
        session.commit()
        return run.id


def _persist_tier_results(
    session: Session, run: EvaluationRun, outcomes: list[TierOutcome], golden
) -> None:
    ev_dir = results_dir() / "runs" / run.id
    ev_dir.mkdir(parents=True, exist_ok=True)
    for i, o in enumerate(outcomes):
        evidence_path = ev_dir / f"{i:02d}-{o.tier.value}{'-' + o.condition if o.condition else ''}.json"
        evidence_path.write_text(
            json.dumps(
                {
                    "tier": o.tier.value,
                    "condition": o.condition,
                    "metrics": o.metrics,
                    "threshold": o.threshold,
                    "passed": o.passed,
                    "evidence": o.evidence,
                    "golden_set_checksum": golden.checksum if golden else None,
                },
                indent=2,
                default=str,
            )
        )
        session.add(
            TierResult(
                run_id=run.id,
                tier=o.tier,
                condition=Condition(o.condition) if o.condition else None,
                metrics=o.metrics,
                threshold=o.threshold,
                passed=o.passed,
                evidence_ref=str(evidence_path),
                dataset_checksum=(golden.checksum if golden else "") or "",
            )
        )


def _regenerate_card(
    session: Session, version_id: str, model_name: str, sandbox_mode: str | None
) -> None:
    """T045-047: rebuild machine blocks from stored results; preserve human text."""
    version = session.get(ModelVersion, version_id)
    runs = session.exec(
        select(EvaluationRun)
        .where(EvaluationRun.model_version_id == version_id)
        .order_by(EvaluationRun.started_at)
    ).all()
    latest = runs[-1] if runs else None
    tier_rows: list[dict] = []
    adjudications: list[dict] = []
    if latest:
        for tr in session.exec(select(TierResult).where(TierResult.run_id == latest.id)).all():
            tier_rows.append(
                {
                    "tier": tr.tier.value,
                    "condition": tr.condition.value if tr.condition else None,
                    "metrics": tr.metrics,
                    "threshold": tr.threshold,
                    "passed": tr.passed,
                }
            )
        for adj in session.exec(
            select(AdjudicationRecord).where(AdjudicationRecord.run_id == latest.id)
        ).all():
            adjudications.append(
                {
                    "decision": adj.decision.value,
                    "reviewer": adj.reviewer,
                    "rationale": adj.rationale,
                    "decided_at": adj.decided_at.isoformat(),
                    "trigger": adj.trigger,
                }
            )
    if sandbox_mode is None and latest:
        # regeneration outside the run (e.g. adjudication decision): recover
        # the recorded isolation mode from the persisted evidence rather than
        # downgrading the card to `to be confirmed`
        for tr in session.exec(select(TierResult).where(TierResult.run_id == latest.id)).all():
            try:
                evidence = json.loads(Path(tr.evidence_ref).read_text())
                sandbox_mode = (evidence.get("evidence") or {}).get("sandbox_mode")
            except (OSError, json.JSONDecodeError):
                continue
            if sandbox_mode:
                break
    golden_name = None
    if latest and latest.golden_set_id:
        gs = session.get(GoldenTestSet, latest.golden_set_id)
        golden_name = gs.name if gs else latest.golden_set_id
    existing = session.exec(
        select(ModelCard).where(ModelCard.model_version_id == version_id)
    ).first()
    inputs = cards.CardInputs(
        model_name=model_name,
        verdict=latest.verdict.value if latest and latest.verdict else None,
        evaluated_at=latest.finished_at if latest else None,
        harness_version=HARNESS_VERSION,
        sandbox_mode=sandbox_mode,
        golden_set=(
            {
                "name": golden_name,
                "version": latest.golden_set_version,
                "checksum": latest.golden_set_checksum,
            }
            if latest and latest.golden_set_id
            else None
        ),
        tier_results=tier_rows,
        framework=version.framework,
        declared_sources=list(version.declared_sources or []),
        artifact_digest=cards.artifact_digest(version.artifact_ref),
        adjudications=adjudications,
    )
    markdown, missing = cards.generate(
        inputs, existing_card=existing.human_sections + existing.machine_blocks if existing else None
    )
    human = cards.split_human_sections(markdown)
    machine = markdown[len(human):] if markdown.startswith(human) else markdown
    if existing:
        existing.human_sections = human
        existing.machine_blocks = machine
        existing.missing_fields = missing
        existing.generated_at = utcnow()
        session.add(existing)
    else:
        session.add(
            ModelCard(
                model_version_id=version_id,
                human_sections=human,
                machine_blocks=machine,
                missing_fields=missing,
            )
        )
    audit.record(
        session,
        actor="orchestrator",
        action="model-card-generated",
        target_ref=f"model_version:{version_id}",
    )


def reevaluate_for_golden_set(golden_set: GoldenTestSet) -> list[str]:
    """FR-004/T059: a golden-set update flags previously evaluated versions of
    the same class for re-evaluation and re-enqueues them. Also rescues
    versions of this class stuck `pending` after a no-golden-set infra run —
    the first registration for a class must pick those up."""
    flagged: list[str] = []
    with Session(get_engine()) as session:
        prior_ids = {
            s.id
            for s in session.exec(
                select(GoldenTestSet).where(
                    GoldenTestSet.model_class == golden_set.model_class,
                    GoldenTestSet.id != golden_set.id,
                )
            ).all()
        }
        runs = session.exec(select(EvaluationRun)).all()
        reeval_ids = {r.model_version_id for r in runs if r.golden_set_id in prior_ids}
        stuck_ids = {
            r.model_version_id for r in runs if r.golden_set_id is None and not r.infra_ok
        }
        for vid in reeval_ids | stuck_ids:
            version = session.get(ModelVersion, vid)
            if version is None:
                continue
            model = session.get(Model, version.model_id)
            if model is None or model.model_class != golden_set.model_class:
                continue
            eligible = (
                vid in reeval_ids
                and version.status
                in (
                    ModelStatus.approved,
                    ModelStatus.rejected,
                    # FR-004: a case still awaiting adjudication is re-evaluated
                    # against the new set so the reviewer never decides on stale
                    # evidence (pending_adjudication → evaluating is legal)
                    ModelStatus.pending_adjudication,
                )
            ) or (vid in stuck_ids and version.status is ModelStatus.pending)
            if not eligible:
                continue
            # status stays put until the re-run starts (approved/pending →
            # evaluating are legal transitions); the audit event records the flag
            audit.record(
                session,
                actor="orchestrator",
                action="re-evaluation-flagged:golden-set-update",
                target_ref=f"model_version:{vid}",
                checksum=golden_set.checksum,
            )
            flagged.append(vid)
        session.commit()
    for vid in flagged:
        enqueue_evaluation(vid)
    return flagged
