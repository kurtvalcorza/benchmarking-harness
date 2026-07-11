"""Durable-work reconciliation diagnostics (T059, US4).

Surfaces the operational health of the transactional outbox and the evidence
store so an operator (and the authenticated readiness probe) can see stuck work
instead of discovering it by absence:

- *stuck intents*: claimed with an EXPIRED lease (a worker died mid-run) or a
  large backlog of failed intents — both need the dispatcher / an operator.
- *orphaned evidence*: staging directories left behind by a crash between
  ``EvidenceStage.stage`` and ``publish``/``discard`` — harmless bytes with no
  DB row, safe to sweep.

Read-only and cheap: this reports, it does not mutate. The dispatcher
(`dispatcher.reclaim_expired_leases`) performs the actual recovery.
"""

from pathlib import Path

from sqlmodel import Session, func, select

from app.db.enums import JobState
from app.db.models import JobIntent, TierResult, utcnow
from app.db.repositories import get_engine


def intent_health() -> dict:
    """Counts by state plus the actionable `stuck` figure (claimed with an
    expired lease). A non-zero `stuck`/`failed` count is an operator signal."""
    with Session(get_engine()) as session:
        now = utcnow()
        counts: dict[str, int] = {}
        for state in JobState:
            counts[state.value] = (
                session.exec(
                    select(func.count())
                    .select_from(JobIntent)
                    .where(JobIntent.state == state)
                ).one()
                or 0
            )
        # any non-terminal leased intent past its lease is stranded work
        leased_states = (JobState.dispatching, JobState.dispatched, JobState.claimed)
        stuck = (
            session.exec(
                select(func.count())
                .select_from(JobIntent)
                .where(
                    JobIntent.state.in_(leased_states),  # type: ignore[attr-defined]
                    JobIntent.leased_until.is_not(None),  # type: ignore[union-attr]
                    JobIntent.leased_until < now,  # type: ignore[operator]
                )
            ).one()
            or 0
        )
    return {"by_state": counts, "stuck": int(stuck), "failed": int(counts.get("failed", 0))}


def orphaned_evidence(results_root: Path) -> list[str]:
    """Staging directories with no corresponding published run — a crash left
    them behind. Returns the run ids (directory names) still staged."""
    staging = Path(results_root) / "staging"
    if not staging.exists():
        return []
    orphans: list[str] = []
    with Session(get_engine()) as session:
        for child in staging.iterdir():
            if not child.is_dir():
                continue
            has_results = session.exec(
                select(TierResult).where(TierResult.run_id == child.name).limit(1)
            ).first()
            # a staging dir whose run never persisted (or persisted and should
            # have been cleaned) is orphaned evidence
            orphans.append(child.name) if not has_results else None
    return orphans


def summary(results_root: Path) -> dict:
    """Compact health object for logs and the authenticated readiness probe."""
    health = intent_health()
    orphans = orphaned_evidence(results_root)
    degraded = health["stuck"] > 0 or health["failed"] > 0 or bool(orphans)
    return {
        "status": "degraded" if degraded else "ready",
        "intents": health,
        "orphaned_evidence": len(orphans),
    }
