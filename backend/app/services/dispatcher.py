"""Leased outbox dispatcher (T056, US4).

Publishes durable *pending* JobIntents to the transport, reclaims *expired*
leases (a worker that claimed an intent and then died), and honours
retry/backoff via each intent's `available_at`. This is what makes the outbox
durable: a submission commits its intent atomically, and even if the in-request
publish is lost to a broker outage the dispatcher re-publishes it here.

Concurrency: on PostgreSQL the pending scan takes `FOR UPDATE SKIP LOCKED` row
locks so parallel dispatchers never double-lease the same intent. On SQLite
(tests / offline demo) there is a single writer, so a plain guarded update is
sufficient and the lock clause is omitted (SQLite has no row-level locking).
"""

from datetime import timedelta

from sqlmodel import Session, select

from app.db.enums import JobState, ModelStatus
from app.db.models import JobIntent, ModelVersion, utcnow
from app.db.repositories import get_engine
from app.services import audit, jobs


def _supports_row_locks(session: Session) -> bool:
    return session.get_bind().dialect.name != "sqlite"


# Non-terminal states that hold a lease and can therefore strand work if their
# owner dies: a publisher crashing mid-dispatch (`dispatching`/`dispatched`) or a
# worker dying mid-run (`claimed`). `completed`/`failed` are terminal; `pending`
# holds no lease.
_LEASED_STATES = (JobState.dispatching, JobState.dispatched, JobState.claimed)


def reclaim_expired_leases() -> int:
    """Return any non-terminal intent whose lease expired to `pending` so it can
    be re-dispatched — covers a publisher that died mid-dispatch AND a worker
    that died mid-run. Returns the count reclaimed."""
    reclaimed = 0
    with Session(get_engine()) as session:
        now = utcnow()
        stmt = select(JobIntent).where(
            JobIntent.state.in_(_LEASED_STATES),  # type: ignore[attr-defined]
            JobIntent.leased_until.is_not(None),  # type: ignore[union-attr]
            JobIntent.leased_until < now,  # type: ignore[operator]
        )
        for intent in session.exec(stmt).all():
            was_claimed = intent.state is JobState.claimed
            intent.state = JobState.pending
            intent.leased_until = None
            intent.last_error = "lease expired; reclaimed for re-dispatch"
            session.add(intent)
            reclaimed += 1
            if was_claimed:
                # a `claimed` intent's worker had set its ModelVersion to
                # `evaluating` and then died (the lease is what expired). Release
                # that stale mutex so the re-dispatch can re-run it — otherwise
                # the re-run hits an illegal evaluating→evaluating transition and
                # the intent poison-loops forever (never recovering the version).
                # The long lease (LEASE_SECONDS) guarantees this only fires for a
                # genuinely dead worker, never a slow-but-alive one.
                version = session.get(ModelVersion, intent.model_version_id)
                if version is not None and version.status is ModelStatus.evaluating:
                    version.status = ModelStatus.pending
                    session.add(version)
                    audit.record(
                        session,
                        actor="dispatcher",
                        action="stale-evaluating-reset:lease-expired",
                        target_ref=f"model_version:{version.id}",
                    )
        session.commit()
    return reclaimed


def dispatch_pending(limit: int = 50) -> list[str]:
    """Lease and publish up to `limit` eligible pending intents. Returns the
    intent ids published. Intents move to `dispatched` under a lease before the
    transport publish, so a crash between lease and publish is reclaimed rather
    than lost or duplicated."""
    from app.services import orchestrator

    to_publish: list[tuple[str, str]] = []
    with Session(get_engine()) as session:
        now = utcnow()
        stmt = (
            select(JobIntent)
            .where(
                JobIntent.state == JobState.pending,
                JobIntent.available_at <= now,
            )
            .order_by(JobIntent.available_at)
            .limit(limit)
        )
        if _supports_row_locks(session):
            stmt = stmt.with_for_update(skip_locked=True)
        for intent in session.exec(stmt).all():
            intent.state = JobState.dispatching
            intent.dispatched_at = now
            intent.leased_until = now + timedelta(seconds=jobs.LEASE_SECONDS)
            session.add(intent)
            to_publish.append((intent.id, intent.model_version_id))
        session.commit()

    published: list[str] = []
    for intent_id, version_id in to_publish:
        try:
            _mark_dispatched(intent_id)
            orchestrator.dispatch_intent(intent_id, version_id)
            published.append(intent_id)
        except Exception as e:  # noqa: BLE001 — publish failure is retryable
            jobs.fail_intent(intent_id, None, error=f"dispatch:{e}", retryable=True)
    return published


def _mark_dispatched(intent_id: str) -> None:
    with Session(get_engine()) as session:
        intent = session.get(JobIntent, intent_id)
        if intent is not None and intent.state is JobState.dispatching:
            intent.state = JobState.dispatched
            session.add(intent)
            session.commit()


def run_once(limit: int = 50) -> dict:
    """One dispatcher sweep: reclaim expired leases, then publish pending
    intents. Returns a small summary for logs/readiness."""
    reclaimed = reclaim_expired_leases()
    published = dispatch_pending(limit)
    return {"reclaimed": reclaimed, "published": len(published), "intent_ids": published}
