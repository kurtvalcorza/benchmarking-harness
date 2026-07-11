"""SQLModel entities per data-model.md.

Append-only entities (EvaluationRun, TierResult, AdjudicationRecord, AuditEvent,
ReevaluationClaim) are enforced at the repository layer (repositories.py), not
here.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import JSON, Column, Field, SQLModel

from app.db.enums import Condition, Decision, ModelClass, ModelStatus, Tier, Verdict


def _uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


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
    reviewer: str  # required (FR-013)
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


APPEND_ONLY_TABLES = (
    EvaluationRun,
    TierResult,
    AdjudicationRecord,
    AuditEvent,
    ReevaluationClaim,
)
