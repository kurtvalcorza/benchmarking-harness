"""Durable job intents — the transactional-outbox core (T054/T058, US4).

A `JobIntent` is created INSIDE the same database transaction that writes the
model version (submission) or the re-evaluation claim, so a durable domain
record can never exist without its evaluation intent — there is no dual-write
gap between "committed the work" and "queued the work" (data-model.md
§Transaction boundaries).

A separate dispatcher (`dispatcher.py`) publishes pending intents to the
transport. A worker *claims* an intent before running it and *completes* it in
the same transaction that persists the EvaluationRun, so:

- a duplicate transport delivery of a `completed` intent performs NO new work;
- a claim that dies mid-run leaves an expired lease the dispatcher reclaims;
- the idempotency key is deterministic from the logical request, so a duplicate
  create returns the existing intent.

All state transitions go through ORM instances (repositories.py append-only
guard covers JobAttempt; JobIntent is intentionally mutable).
"""

import os
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.db.enums import JobKind, JobOutcome, JobReason, JobState
from app.db.models import JobAttempt, JobIntent, as_utc, utcnow
from app.db.repositories import get_engine

# How long a claim holds an intent before the dispatcher may reclaim it. Matches
# the sandbox wall-clock ceiling so a legitimately long run is never stolen.
LEASE_SECONDS = int(os.environ.get("HARNESS_JOB_LEASE_SECONDS", "1800"))
# Exponential backoff between retryable failures (bounded).
RETRY_BASE_SECONDS = int(os.environ.get("HARNESS_JOB_RETRY_BASE_SECONDS", "30"))
RETRY_CAP_SECONDS = int(os.environ.get("HARNESS_JOB_RETRY_CAP_SECONDS", "900"))
MAX_ATTEMPTS = int(os.environ.get("HARNESS_JOB_MAX_ATTEMPTS", "5"))


def idempotency_key(
    reason: JobReason,
    model_version_id: str,
    golden_set_id: str | None,
    occasion: str | None = None,
) -> str:
    """Deterministic key for one logical evaluation request. A submission maps
    to exactly one key so a duplicate submission delivery collapses onto one
    row; an `occasion` (e.g. a re-evaluation claim id) distinguishes genuinely
    separate re-dispatch occasions that are deduplicated upstream."""
    base = f"{reason.value}:{model_version_id}:{golden_set_id or '-'}"
    return f"{base}:{occasion}" if occasion else base


def create_intent(
    session: Session,
    *,
    model_version_id: str,
    reason: JobReason,
    golden_set_id: str | None = None,
    occasion: str | None = None,
) -> JobIntent:
    """Create (or return the existing) intent for a logical request.

    MUST be called inside the caller's transaction so the intent commits
    atomically with the domain write. Flushes in a savepoint so a concurrent
    creator racing the unique(idempotency_key) constraint does not poison the
    surrounding transaction.
    """
    key = idempotency_key(reason, model_version_id, golden_set_id, occasion)
    existing = session.exec(
        select(JobIntent).where(JobIntent.idempotency_key == key)
    ).first()
    if existing is not None:
        return existing
    intent = JobIntent(
        kind=JobKind.evaluate_model_version,
        model_version_id=model_version_id,
        golden_set_id=golden_set_id,
        reason=reason,
        idempotency_key=key,
        state=JobState.pending,
    )
    session.add(intent)
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError:
        return session.exec(
            select(JobIntent).where(JobIntent.idempotency_key == key)
        ).first()
    return intent


@dataclass
class Claim:
    intent_id: str
    attempt_id: str
    attempt_number: int


def claim_intent(
    intent_id: str, *, worker_id: str, transport_job_id: str | None = None
) -> Claim | None:
    """Atomically transition an intent to `claimed` and open a JobAttempt.

    Returns None when the intent is already `completed` or under an unexpired
    claim — a DUPLICATE delivery that must run no evaluation. The claim commits
    durably BEFORE the (long) evaluation runs, so a mid-run crash leaves an
    expired lease the dispatcher can reclaim rather than a lost job.
    """
    with Session(get_engine()) as session:
        intent = session.get(JobIntent, intent_id)
        if intent is None:
            return None
        now = utcnow()
        leased_until = as_utc(intent.leased_until)  # SQLite returns naive datetimes
        lease_live = leased_until is not None and leased_until > now
        if intent.state is JobState.completed:
            _record_duplicate(session, intent, worker_id, transport_job_id)
            session.commit()
            return None
        if intent.state is JobState.claimed and lease_live:
            _record_duplicate(session, intent, worker_id, transport_job_id)
            session.commit()
            return None
        intent.attempt_count += 1
        attempt = JobAttempt(
            job_intent_id=intent.id,
            attempt_number=intent.attempt_count,
            worker_id=worker_id,
            transport_job_id=transport_job_id,
            outcome=JobOutcome.claimed,
        )
        intent.state = JobState.claimed
        intent.claimed_at = now
        intent.leased_until = now + timedelta(seconds=LEASE_SECONDS)
        session.add(intent)
        session.add(attempt)
        session.commit()
        return Claim(intent_id=intent.id, attempt_id=attempt.id, attempt_number=attempt.attempt_number)


def _record_duplicate(
    session: Session, intent: JobIntent, worker_id: str, transport_job_id: str | None
) -> None:
    """Log a no-op duplicate delivery as an append-only attempt for the audit
    trail without advancing the intent."""
    intent.attempt_count += 1
    session.add(
        JobAttempt(
            job_intent_id=intent.id,
            attempt_number=intent.attempt_count,
            worker_id=worker_id,
            transport_job_id=transport_job_id,
            started_at=utcnow(),
            finished_at=utcnow(),
            outcome=JobOutcome.duplicate,
        )
    )
    session.add(intent)


def complete_intent(
    session: Session, intent_id: str, attempt_id: str | None, *, run_id: str | None
) -> None:
    """Mark the intent completed and finalize its attempt WITHIN the caller's
    completion transaction, so the terminal intent state and the EvaluationRun
    commit together (data-model.md §Successful evaluation completion)."""
    intent = session.get(JobIntent, intent_id)
    if intent is not None:
        intent.state = JobState.completed
        intent.completed_at = utcnow()
        intent.leased_until = None
        intent.last_error = None
        session.add(intent)
    if attempt_id is not None:
        attempt = session.get(JobAttempt, attempt_id)
        if attempt is not None:
            attempt.finished_at = utcnow()
            attempt.outcome = JobOutcome.completed
            attempt.run_id = run_id
            session.add(attempt)


def fail_intent(
    intent_id: str,
    attempt_id: str | None,
    *,
    error: str,
    retryable: bool,
) -> None:
    """Finalize a failed attempt in its own transaction. A retryable failure
    returns the intent to `pending` with exponential backoff (up to
    MAX_ATTEMPTS); a terminal failure parks it in `failed`."""
    with Session(get_engine()) as session:
        intent = session.get(JobIntent, intent_id)
        if intent is None:
            return
        attempt = session.get(JobAttempt, attempt_id) if attempt_id else None
        exhausted = intent.attempt_count >= MAX_ATTEMPTS
        will_retry = retryable and not exhausted
        if attempt is not None:
            attempt.finished_at = utcnow()
            attempt.outcome = (
                JobOutcome.retryable_failure if will_retry else JobOutcome.terminal_failure
            )
            attempt.error_code = (error or "")[:120]
            session.add(attempt)
        intent.last_error = (error or "")[:500]
        intent.leased_until = None
        if will_retry:
            backoff = min(RETRY_CAP_SECONDS, RETRY_BASE_SECONDS * (2 ** (intent.attempt_count - 1)))
            intent.state = JobState.pending
            intent.available_at = utcnow() + timedelta(seconds=backoff)
        else:
            intent.state = JobState.failed
        session.add(intent)
        session.commit()
