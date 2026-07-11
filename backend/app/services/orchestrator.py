"""Evaluation orchestrator (T052/T055/US4 durable dispatch).

Runs the three tiers IN ORDER, halts on a hard tier failure (FR-007), persists
the run + per-tier results append-only, applies the FR-012 flag rule,
transitions ModelVersion.status, and (re)generates the Model Card — the run,
tiers, status, audit, card, AND the durable JobIntent completion all commit in
ONE transaction (data-model.md §Successful evaluation completion), so there is
never a completed run without its current card, nor a completed intent without
its run.

Durable dispatch (US4): every evaluation is backed by a `JobIntent` (the
transactional outbox). Submission creates the intent inside its own transaction;
the worker/inline executor CLAIMS the intent before running and COMPLETES it in
the completion transaction, so a duplicate transport delivery of a completed
intent performs no new work.

All inference is dispatched through the no-egress sandbox runner (D1) — this
process never loads model weights.

Execution modes:
- HARNESS_EVAL_MODE=rq (default): enqueue on Redis/RQ; worker/main.py consumes.
- HARNESS_EVAL_MODE=inline: run synchronously in-process (tests, offline demo).
"""

import json
import os
import uuid
from pathlib import Path

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.db.enums import Condition, JobReason, JobState, ModelClass, ModelStatus, Tier
from app.db.models import (
    AdjudicationRecord,
    EvaluationRun,
    GoldenTestSet,
    JobIntent,
    Model,
    ModelCard,
    ModelVersion,
    ReevaluationClaim,
    TierResult,
    utcnow,
)
from app.db.repositories import get_engine
from app.services import audit, jobs
from app.services.config import get_threshold
from app.services.evidence_store import EvidenceStage
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


# --------------------------------------------------------------------------- #
# Durable dispatch (US4 transactional outbox)                                  #
# --------------------------------------------------------------------------- #


def dispatch_intent(intent_id: str, version_id: str) -> None:
    """Publish a durable intent to the transport. Inline mode runs it now
    through the SAME claim/complete code the worker uses (T058); rq mode
    enqueues `evaluate_intent`. Failures here are non-fatal: the intent is
    already durable, so the dispatcher/reconciler reclaims a lost publish."""
    if eval_mode() == "inline":
        evaluate_intent(intent_id)
        return
    from redis import Redis
    from rq import Queue

    q = Queue("evaluations", connection=Redis.from_url(
        os.environ.get("HARNESS_REDIS_URL", "redis://localhost:6379/0")
    ))
    q.enqueue("app.services.orchestrator.evaluate_intent", intent_id, job_timeout=7200)


def enqueue_evaluation(version_id: str) -> None:
    """FR-003 / re-evaluation dispatch primitive. Publishes the version's
    outstanding durable intent — the one the claim-winner created in its own
    transaction (submission / golden-set update / mid-run staleness) — so a lost
    publish is recovered by re-dispatching the SAME intent, never by minting a
    duplicate. Falls back to a fresh operator intent only when none is pending
    (a bare operator retry). Single positional arg so the recovery reconciler
    and tests can drive it uniformly."""
    with Session(get_engine()) as session:
        pending = session.exec(
            select(JobIntent)
            .where(
                JobIntent.model_version_id == version_id,
                JobIntent.state == JobState.pending,
            )
            .order_by(JobIntent.created_at)
        ).all()
        intent = pending[-1] if pending else None
        if intent is None:
            intent = jobs.create_intent(
                session,
                model_version_id=version_id,
                reason=JobReason.operator_retry,
                occasion=uuid.uuid4().hex,
            )
            session.commit()
        intent_id = intent.id
    dispatch_intent(intent_id, version_id)


def evaluate_intent(intent_id: str) -> str | None:
    """Worker/inline entrypoint: resolve the intent's version and evaluate it
    under the intent's claim. A missing intent is a no-op."""
    with Session(get_engine()) as session:
        intent = session.get(JobIntent, intent_id)
        if intent is None:
            return None
        version_id = intent.model_version_id
    return evaluate_version(version_id, intent_id=intent_id)


def _latest_golden_set(session: Session, model_class: ModelClass) -> GoldenTestSet | None:
    sets = session.exec(
        select(GoldenTestSet).where(GoldenTestSet.model_class == model_class)
    ).all()
    return max(sets, key=lambda s: s.registered_at) if sets else None


def _claim_reevaluation(
    session: Session, version_id: str, golden_set_id: str
) -> bool:
    """Atomically claim one automatic retry for a version/set pair."""
    try:
        # Keep a uniqueness collision local to the savepoint so callers can
        # still commit their surrounding audit transaction.
        with session.begin_nested():
            session.add(
                ReevaluationClaim(
                    model_version_id=version_id,
                    golden_set_id=golden_set_id,
                )
            )
            session.flush()
    except IntegrityError:
        return False
    return True


def recover_orphaned_reevaluations() -> list[str]:
    """Re-enqueue retries whose claim committed but whose job was lost.

    `_claim_reevaluation` durably commits the claim BEFORE `enqueue_evaluation`
    runs, so a crash or broker outage in that window leaves a claim with no job
    — and because claims are append-only, nothing can ever re-claim that pair.
    This reconciles that gap: any claim with no evaluation run started at/after
    it, for a version not currently `evaluating`, is re-enqueued. It runs at
    startup (worker boot in rq mode, app lifespan in inline mode).

    Idempotent: once the retry run persists (its `started_at` lands at/after the
    claim's `created_at`) the pair is satisfied and skipped on the next pass. A
    benign duplicate is possible if two recoverers race a pre-existing orphan;
    that only ever adds a run, never loses one.
    """
    orphaned: list[str] = []
    with Session(get_engine()) as session:
        claims = session.exec(select(ReevaluationClaim)).all()
        if not claims:
            return orphaned
        latest_claim_at: dict[str, object] = {}
        for c in claims:
            prev = latest_claim_at.get(c.model_version_id)
            if prev is None or c.created_at > prev:
                latest_claim_at[c.model_version_id] = c.created_at
        latest_run_at: dict[str, object] = {}
        for r in session.exec(select(EvaluationRun)).all():
            prev = latest_run_at.get(r.model_version_id)
            if prev is None or r.started_at > prev:
                latest_run_at[r.model_version_id] = r.started_at
        for vid, claim_at in latest_claim_at.items():
            run_at = latest_run_at.get(vid)
            if run_at is not None and run_at >= claim_at:
                continue  # a run happened at/after the claim → the retry ran
            version = session.get(ModelVersion, vid)
            if version is None or version.status is ModelStatus.evaluating:
                continue  # version gone, or a job is already in flight
            orphaned.append(vid)
    for vid in orphaned:
        enqueue_evaluation(vid)
    return orphaned


def evaluate_version(version_id: str, *, intent_id: str | None = None) -> str | None:
    """Run the full three-tier evaluation for a ModelVersion. Returns run id.

    When `intent_id` is supplied the run executes under that JobIntent's claim:
    a duplicate transport delivery (intent already completed / under a live
    claim) is a NO-OP that returns None without re-running the model (T057).
    """
    claim: jobs.Claim | None = None
    if intent_id is not None:
        claim = jobs.claim_intent(intent_id, worker_id=_worker_id())
        if claim is None:
            return None  # duplicate delivery — perform no evaluation

    with Session(get_engine()) as session:
        version = session.get(ModelVersion, version_id)
        if version is None:
            if claim is not None:
                jobs.fail_intent(
                    intent_id, claim.attempt_id, error="unknown model version", retryable=False
                )
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
    run_id = run.id  # capture pre-commit: the instance detaches after the session closes
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
                    label_map=dict(golden.label_map or {}),
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

    # Stage tier evidence to a temp area + digest it BEFORE the completion
    # transaction; publish atomically just before commit, compensate on failure
    # (T051) — a rolled-back run leaves no evidence, a committed run never lacks
    # the evidence its TierResults reference.
    stage = EvidenceStage(results_root=results_dir(), run_id=run_id)
    try:
        with Session(get_engine()) as session:
            version = session.get(ModelVersion, version_id)
            if infra_error:
                # infra failure ≠ model failure (spec edge case): no model verdict
                run.infra_ok = False
                run.verdict = None
                run.flag_trigger = f"infra:{infra_error[:300]}"
                session.add(run)
                _persist_tier_results(session, run, outcomes, golden, stage)
                version.status = ModelStatus.pending  # eligible for retry/resubmission
                audit.record(
                    session,
                    actor="orchestrator",
                    action="run-infra-failure",
                    target_ref=f"run:{run.id}",
                )
                session.add(version)
                # complete the intent in the SAME txn: an infra run is a real
                # (non-retryable-by-redelivery) outcome — the version is back to
                # `pending` and the durable claim/recovery path owns any retry
                if claim is not None:
                    jobs.complete_intent(session, intent_id, claim.attempt_id, run_id=run.id)
                _upsert_card(
                    session, version_id, model_name, sandbox_mode_used, outcomes, run, golden
                )
                stage.publish()
                session.commit()
            else:
                score = score_run(
                    outcomes=outcomes,
                    safety_breach=safety_breach,
                    declared_sources=declared_sources,
                )
                run.verdict = score.verdict
                run.flag_trigger = score.flag_trigger
                session.add(run)
                _persist_tier_results(session, run, outcomes, golden, stage)

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
                # ONE transaction: run + tiers + status + audit + card + intent
                # completion (data-model.md §Successful evaluation completion)
                if claim is not None:
                    jobs.complete_intent(session, intent_id, claim.attempt_id, run_id=run.id)
                _upsert_card(
                    session, version_id, model_name, sandbox_mode_used, outcomes, run, golden
                )
                stage.publish()
                session.commit()
    except Exception as e:
        # result persistence itself failed (bad results dir, permissions, full
        # disk) — compensate the staged evidence, never leave the version stuck
        # `evaluating` with no run, and let the durable intent retry
        stage.discard()
        if claim is not None:
            jobs.fail_intent(
                intent_id, claim.attempt_id, error=f"persist:{e}", retryable=True
            )
        _reset_to_pending(version_id, "run-persistence-failure")
        raise

    # A golden-set change may have landed while this run was IN FLIGHT — either
    # a newer set replaced the one we scored against, or the FIRST set for the
    # class appeared during a no-golden run. Both are invisible to
    # reevaluate_for_golden_set (its candidates come from persisted runs), so
    # re-enqueue against the now-current set. Bounded: each re-run captures the
    # then-current set, so this stops as soon as registrations stop arriving.
    with Session(get_engine()) as session:
        latest = _latest_golden_set(session, model_class)
        stale = latest is not None and (golden is None or latest.id != golden.id)
        claimed = stale and _claim_reevaluation(session, version_id, latest.id)
        if claimed:
            # durable outbox intent for the mid-run re-evaluation, created IN THE
            # SAME transaction as the claim (T055) so a lost publish is recoverable
            jobs.create_intent(
                session,
                model_version_id=version_id,
                reason=JobReason.mid_run_staleness,
                golden_set_id=latest.id,
            )
            audit.record(
                session,
                actor="orchestrator",
                action="re-evaluation-flagged:golden-set-changed-mid-run",
                target_ref=f"model_version:{version_id}",
                checksum=latest.checksum,
            )
            session.commit()
    if claimed:
        enqueue_evaluation(version_id)
    return run_id


def _worker_id() -> str:
    """Stable-per-process claim owner for the audit trail."""
    return f"{os.environ.get('HOSTNAME', 'local')}:{os.getpid()}"


def _reset_to_pending(version_id: str, reason: str) -> None:
    try:
        with Session(get_engine()) as session:
            version = session.get(ModelVersion, version_id)
            if version is not None and version.status is ModelStatus.evaluating:
                version.status = ModelStatus.pending
                session.add(version)
                audit.record(
                    session,
                    actor="orchestrator",
                    action=reason,
                    target_ref=f"model_version:{version_id}",
                )
                session.commit()
    except Exception:
        pass  # best effort — the original exception is what matters


def _persist_tier_results(
    session: Session,
    run: EvaluationRun,
    outcomes: list[TierOutcome],
    golden,
    stage: EvidenceStage,
) -> None:
    dataset_checksum = (golden.checksum if golden else "") or ""
    for i, o in enumerate(outcomes):
        name = f"{o.tier.value}{'-' + o.condition if o.condition else ''}"
        # US2: the tier stamps evaluator.dataset_checksum with ITS OWN dataset
        # (Tier 1 = benchmark, Tier 2 = Golden Set); only fill a missing value
        # here, never overwrite the tier's correct one.
        evaluator = dict(o.evaluator) if o.evaluator else None
        if evaluator is not None and not evaluator.get("dataset_checksum"):
            evaluator["dataset_checksum"] = dataset_checksum
        evidence = dict(o.evidence) if o.evidence else {}
        metrics = dict(o.metrics) if o.metrics else {}
        # US5/T066: persist grounding attribution as its OWN content-addressed
        # evidence artifact and stamp the measured GroundingEvidence with the
        # resolvable evidence_ref + evidence_digest (the raw samples never live
        # in the metrics column).
        grounding_samples = evidence.pop("grounding_samples", None)
        grounding = metrics.get("grounding")
        if grounding_samples and isinstance(grounding, dict) and grounding.get("status") == "measured":
            _g_ref, g_digest = stage.stage(
                i, f"{o.tier.value}-grounding", {"method": grounding.get("method"), "samples": grounding_samples}
            )
            # CONTENT-addressed reference: identical model+data → identical
            # grounding evidence, so the ref must be reproducible (a per-run file
            # path would break SC-004). The artifact at `_g_ref` hashes to
            # g_digest, so `sha256:<digest>` resolves to it in a content store.
            grounding = {
                **grounding,
                "evidence_ref": f"sha256:{g_digest}",
                "evidence_digest": g_digest,
            }
            metrics["grounding"] = grounding
        payload = {
            "tier": o.tier.value,
            "condition": o.condition,
            "metrics": metrics,
            "threshold": o.threshold,
            "passed": o.passed,
            "coverage": o.coverage,
            "evaluator": evaluator,
            "evidence": evidence,
            "golden_set_checksum": golden.checksum if golden else None,
        }
        evidence_ref, evidence_digest = stage.stage(i, name, payload)
        session.add(
            TierResult(
                run_id=run.id,
                tier=o.tier,
                condition=Condition(o.condition) if o.condition else None,
                metrics=metrics,
                threshold=o.threshold,
                passed=o.passed,
                coverage=o.coverage,
                evaluator=evaluator,
                evidence_ref=evidence_ref,
                evidence_digest=evidence_digest,
                dataset_checksum=dataset_checksum,
            )
        )


def _upsert_card(
    session: Session,
    version_id: str,
    model_name: str,
    sandbox_mode: str | None,
    outcomes: list[TierOutcome],
    run: EvaluationRun,
    golden,
) -> None:
    """T050/T052: build the Model Card from EXPLICIT transaction-local inputs
    (this run's in-memory outcomes) and upsert it in the completion transaction
    — never a second commit, never a re-query of half-committed state."""
    version = session.get(ModelVersion, version_id)
    tier_rows = [
        {
            "tier": o.tier.value,
            "condition": o.condition,
            "metrics": o.metrics,
            "threshold": o.threshold,
            "passed": o.passed,
        }
        for o in outcomes
    ]
    golden_block = (
        {
            "name": golden.name,
            "version": run.golden_set_version,
            "checksum": run.golden_set_checksum,
        }
        if golden is not None and run.golden_set_id
        else None
    )
    grounding = next(
        (o.metrics.get("grounding") for o in outcomes if o.tier is Tier.operational_safety),
        None,
    )
    inputs = cards.CardInputs(
        model_name=model_name,
        verdict=run.verdict.value if run.verdict else None,
        flag_trigger=run.flag_trigger,
        evaluated_at=run.finished_at,
        harness_version=HARNESS_VERSION,
        sandbox_mode=sandbox_mode,
        golden_set=golden_block,
        tier_results=tier_rows,
        framework=version.framework,
        declared_sources=list(version.declared_sources or []),
        artifact_digest=cards.artifact_digest(version.artifact_ref),
        adjudications=[],  # a fresh run carries no adjudication yet
        grounding=grounding,
    )
    _write_card(session, version_id, inputs)


def _write_card(session: Session, version_id: str, inputs: cards.CardInputs) -> None:
    existing = session.exec(
        select(ModelCard).where(ModelCard.model_version_id == version_id)
    ).first()
    markdown, missing = cards.generate(
        inputs,
        existing_card=existing.human_sections + existing.machine_blocks if existing else None,
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


def _regenerate_card(
    session: Session, version_id: str, model_name: str, sandbox_mode: str | None
) -> None:
    """Adjudication path: rebuild the machine blocks from STORED results (the
    decision is already flushed in this transaction) and upsert the card in the
    same transaction as the decision (T053). Human sections are preserved."""
    version = session.get(ModelVersion, version_id)
    runs = session.exec(
        select(EvaluationRun)
        .where(EvaluationRun.model_version_id == version_id)
        .order_by(EvaluationRun.started_at)
    ).all()
    latest = runs[-1] if runs else None
    tier_rows: list[dict] = []
    adjudications: list[dict] = []
    grounding: dict | None = None
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
            if tr.tier is Tier.operational_safety and isinstance(tr.metrics, dict):
                grounding = tr.metrics.get("grounding")
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
    inputs = cards.CardInputs(
        model_name=model_name,
        verdict=latest.verdict.value if latest and latest.verdict else None,
        flag_trigger=latest.flag_trigger if latest else None,
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
        grounding=grounding,
    )
    _write_card(session, version_id, inputs)


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
            if not _claim_reevaluation(session, vid, golden_set.id):
                continue
            # durable outbox intent for the re-evaluation, created IN THE SAME
            # transaction as the claim (T055) so a lost enqueue is recoverable
            jobs.create_intent(
                session,
                model_version_id=vid,
                reason=JobReason.golden_set_update,
                golden_set_id=golden_set.id,
            )
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
