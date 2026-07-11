"""SQLModel entities per data-model.md.

Append-only entities (EvaluationRun, TierResult, AdjudicationRecord, AuditEvent,
ReevaluationClaim) are enforced at the repository layer (repositories.py), not
here.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import JSON, Column, Field, SQLModel

from app.db.enums import (
    Condition,
    Decision,
    JobKind,
    JobOutcome,
    JobReason,
    JobState,
    ModelClass,
    ModelStatus,
    Tier,
    Verdict,
)

# Identity assigned to Feature 001 rows that predate authenticated submission
# (data-model.md migration step 3): they carry no verified principal.
LEGACY_PRINCIPAL = "legacy:feature-001"


def _uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


def as_utc(dt: datetime | None) -> datetime | None:
    """Normalize a possibly-naive stored datetime to UTC-aware.

    SQLite drops tzinfo on round-trip, so a datetime read back from the DB is
    naive while `utcnow()` is aware — comparing the two raises. Callers doing
    Python-level datetime comparisons on stored values normalize through here.
    """
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


class Model(SQLModel, table=True):
    # model identity survives concurrent first submissions
    __table_args__ = (UniqueConstraint("name", "model_class"),)

    id: str = Field(default_factory=_uuid, primary_key=True)
    name: str = Field(index=True)
    model_class: ModelClass
    created_at: datetime = Field(default_factory=utcnow)


class ModelVersion(SQLModel, table=True):
    # DB-level guarantee: version identity survives concurrent submissions
    # (the API's read-before-insert check alone is racy)
    __table_args__ = (UniqueConstraint("model_id", "version"),)

    id: str = Field(default_factory=_uuid, primary_key=True)
    model_id: str = Field(foreign_key="model.id", index=True)
    version: str
    artifact_ref: str  # serialized weights location (gitignored store), FR-023
    framework: str  # e.g. pytorch / onnx, FR-023
    declared_sources: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    status: ModelStatus = Field(default=ModelStatus.pending)
    submitted_at: datetime = Field(default_factory=utcnow)
    # FR-001: the verified principal that submitted this version (principal_key =
    # issuer|subject). Legacy rows carry LEGACY_PRINCIPAL until backfilled.
    submitted_by: str = Field(default=LEGACY_PRINCIPAL, index=True)
    # FR-006: the immutable receipt for the finalized artifact upload (feature
    # 002). Nullable during migration; set on every new bounded upload.
    artifact_receipt_id: str | None = Field(
        default=None, foreign_key="artifactreceipt.id"
    )


class GoldenTestSet(SQLModel, table=True):
    # a golden-set version is immutable and unique (FR-004): enforce identity
    # in the DB, not just the registration API's read-before-insert check
    __table_args__ = (UniqueConstraint("name", "version"),)

    id: str = Field(default_factory=_uuid, primary_key=True)
    name: str
    domain: str = "general"
    model_class: ModelClass
    version: str  # immutable; change → new version, triggers re-eval (FR-004)
    manifest_ref: str = ""
    checksum: str  # content hash, stamped on every result (FR-018)
    conditions: list[Condition] = Field(default_factory=list, sa_column=Column(JSON))
    safety_critical_classes: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    recall_floors: dict[str, float] = Field(default_factory=dict, sa_column=Column(JSON))
    label_map: dict[str, str] = Field(default_factory=dict, sa_column=Column(JSON))  # F6
    license: str  # MUST be owned/permissive for committed data (Constitution II)
    is_public: bool = False  # MUST be false (never-public invariant)
    data_ref: str = ""  # local path to fetched data (gitignored)
    registered_at: datetime = Field(default_factory=utcnow)
    # FR-020: the governance principal that registered this set; scopes the
    # "own registrations" status read (security-boundary.md). Legacy default.
    registered_by: str = Field(default=LEGACY_PRINCIPAL, index=True)


class EvaluationRun(SQLModel, table=True):  # 🔒 append-only
    id: str = Field(default_factory=_uuid, primary_key=True)
    model_version_id: str = Field(foreign_key="modelversion.id", index=True)
    harness_version: str = "0.1.0"
    golden_set_id: str | None = None
    golden_set_version: str | None = None
    golden_set_checksum: str | None = None  # FR-018
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    verdict: Verdict | None = None
    infra_ok: bool = True  # distinguishes infra failure from model `fail`
    flag_trigger: str | None = None  # why the run was routed to adjudication (FR-012)


class ReevaluationClaim(SQLModel, table=True):  # 🔒 append-only
    """Exactly one automatic retry per model version and golden set.

    Registration recovery and an in-flight run's post-verdict recheck can both
    discover the same stale version. This durable claim makes those paths race
    safely across processes instead of enqueueing duplicate evaluations.
    """

    __table_args__ = (UniqueConstraint("model_version_id", "golden_set_id"),)

    id: str = Field(default_factory=_uuid, primary_key=True)
    model_version_id: str = Field(foreign_key="modelversion.id", index=True)
    golden_set_id: str = Field(foreign_key="goldentestset.id", index=True)
    created_at: datetime = Field(default_factory=utcnow)


class TierResult(SQLModel, table=True):  # 🔒 append-only
    id: str = Field(default_factory=_uuid, primary_key=True)
    run_id: str = Field(foreign_key="evaluationrun.id", index=True)
    tier: Tier
    condition: Condition | None = None  # Tier 2 has one row per condition (FR-008)
    metrics: dict = Field(default_factory=dict, sa_column=Column(JSON))
    threshold: dict | None = Field(default=None, sa_column=Column(JSON))
    passed: bool | None = None  # null when pending
    evidence_ref: str = ""  # artifacts backing the numbers (Constitution V)
    dataset_checksum: str = ""  # copied from the golden set (FR-018)
    # feature 002 evaluation integrity (data-model.md):
    coverage: dict | None = Field(default=None, sa_column=Column(JSON))  # PredictionCoverage
    evaluator: dict | None = Field(default=None, sa_column=Column(JSON))  # EvaluatorProvenance
    evidence_digest: str | None = None  # SHA-256 of evidence_ref when non-empty


class ModelCard(SQLModel, table=True):
    id: str = Field(default_factory=_uuid, primary_key=True)
    model_version_id: str = Field(foreign_key="modelversion.id", index=True)
    human_sections: str = ""  # preserved across regenerations (FR-014)
    machine_blocks: str = ""  # Benchmark Results + Provenance + Adjudication
    missing_fields: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    generated_at: datetime = Field(default_factory=utcnow)


class AdjudicationRecord(SQLModel, table=True):  # 🔒 append-only
    # exactly ONE permanent decision per run: two reviewers racing the status
    # check cannot both record (the loser gets an IntegrityError → 409)
    __table_args__ = (UniqueConstraint("run_id"),)

    id: str = Field(default_factory=_uuid, primary_key=True)
    run_id: str = Field(foreign_key="evaluationrun.id", index=True)
    trigger: str
    evidence_ref: str = ""
    reviewer: str  # required (FR-013); populated only from Principal.subject
    reviewer_display: str | None = None  # non-authoritative display text (audit readability)
    decision: Decision
    rationale: str  # required, non-empty
    decided_at: datetime = Field(default_factory=utcnow)


class AuditEvent(SQLModel, table=True):  # 🔒 append-only
    id: str = Field(default_factory=_uuid, primary_key=True)
    actor: str
    action: str  # access / checksum-verify / status-change / lifecycle
    target_ref: str
    checksum: str | None = None
    at: datetime = Field(default_factory=utcnow)
    # feature 002 identity + telemetry (data-model.md). MUST NOT hold tokens or
    # model payload bytes.
    request_id: str | None = None
    principal_issuer: str | None = None
    outcome: str | None = None  # success | denied | failure
    audit_metadata: dict | None = Field(default=None, sa_column=Column(JSON))


class ArtifactReceipt(SQLModel, table=True):  # 🔒 immutable
    """Proof that a bounded artifact upload streamed to disk and finalized.

    Created inside the submission transaction (data-model.md); never updated or
    deleted through application repositories.
    """

    id: str = Field(default_factory=_uuid, primary_key=True)
    storage_ref: str = Field(unique=True)  # finalized digest-addressed path/key
    original_filename: str = ""  # sanitized metadata only
    byte_count: int  # >0 and <= configured maximum at ingestion
    sha256: str = Field(index=True)  # lowercase hex
    framework: str
    submitted_by: str
    finalized_at: datetime = Field(default_factory=utcnow)


class JobIntent(SQLModel, table=True):
    """Durable transactional-outbox record: submission/re-evaluation survives a
    Redis outage and duplicate delivery (data-model.md, plan.md durable path).

    NOT append-only — `state` advances through the transition table. Identity is
    the deterministic `idempotency_key`: a duplicate create returns the existing
    intent, and a duplicate transport delivery of `completed` is a no-op.
    """

    __table_args__ = (UniqueConstraint("idempotency_key"),)

    id: str = Field(default_factory=_uuid, primary_key=True)
    kind: JobKind = Field(default=JobKind.evaluate_model_version)
    model_version_id: str = Field(foreign_key="modelversion.id", index=True)
    golden_set_id: str | None = Field(default=None, foreign_key="goldentestset.id")
    reason: JobReason = Field(default=JobReason.submission)
    idempotency_key: str = Field(index=True)
    state: JobState = Field(default=JobState.pending, index=True)
    attempt_count: int = 0
    available_at: datetime = Field(default_factory=utcnow)  # retry/backoff eligibility
    lease_owner: str | None = None  # dispatcher lease holder
    leased_until: datetime | None = None
    last_error: str | None = None  # sanitized bounded message
    created_at: datetime = Field(default_factory=utcnow)
    dispatched_at: datetime | None = None
    claimed_at: datetime | None = None
    completed_at: datetime | None = None


class JobAttempt(SQLModel, table=True):
    """One claim/execution of a JobIntent. Terminalized in its own transaction,
    then treated append-only."""

    __table_args__ = (UniqueConstraint("job_intent_id", "attempt_number"),)

    id: str = Field(default_factory=_uuid, primary_key=True)
    job_intent_id: str = Field(foreign_key="jobintent.id", index=True)
    attempt_number: int  # starts at 1, unique within the intent
    worker_id: str = ""
    transport_job_id: str | None = None  # RQ identifier
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    outcome: JobOutcome | None = None
    run_id: str | None = None  # EvaluationRun produced by successful completion
    error_code: str | None = None


APPEND_ONLY_TABLES = (
    EvaluationRun,
    TierResult,
    AdjudicationRecord,
    AuditEvent,
    ReevaluationClaim,
    ArtifactReceipt,
)
