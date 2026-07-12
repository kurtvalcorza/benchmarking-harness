"""Pydantic response/request schemas mirroring contracts/openapi.yaml."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.db.enums import Condition, Decision, ModelClass, ModelStatus, Tier, Verdict


class ArtifactReceiptOut(BaseModel):
    id: str
    sha256: str
    byte_count: int
    original_filename: str
    finalized_at: datetime


class ModelVersionOut(BaseModel):
    id: str
    model_id: str
    name: str
    model_class: ModelClass
    version: str
    framework: str
    status: ModelStatus
    submitted_at: datetime
    submitted_by: str
    artifact: ArtifactReceiptOut | None = None


class ModelDetailOut(ModelVersionOut):
    declared_sources: list[str] = []
    card_markdown: str | None = None
    missing_card_fields: list[str] = []


class ModelListItemOut(BaseModel):
    """One row of the oversight/history list (GET /models): a submission plus a
    summary of its latest run — verdict, the gated capability metric, and, when a
    run could not evaluate the model, the infra-failure reason (so a submission
    that failed to load is not silently 'pending' with no visible cause)."""

    id: str  # model_version_id
    model_id: str
    name: str
    model_class: ModelClass
    version: str
    framework: str
    status: ModelStatus
    submitted_at: datetime
    submitted_by: str
    latest_verdict: Verdict | None = None
    evaluated_at: datetime | None = None
    infra_ok: bool = True
    infra_error: str | None = None  # surfaced from the latest run when infra_ok is false
    headline_metric: str | None = None  # the capability gate metric, e.g. coco_ap_50_95
    headline_value: float | None = None


class TierResultOut(BaseModel):
    tier: Tier
    condition: Condition | None = None
    metrics: dict
    threshold: dict | None = None
    passed: bool | None = None
    evidence_ref: str = ""
    dataset_checksum: str = ""
    coverage: dict | None = None
    evaluator: dict | None = None
    evidence_digest: str | None = None


class GoldenSetRef(BaseModel):
    id: str | None = None
    version: str | None = None
    checksum: str | None = None


class EvaluationRunOut(BaseModel):
    id: str
    model_version_id: str
    verdict: Verdict | None = None
    golden_set: GoldenSetRef
    started_at: datetime
    finished_at: datetime | None = None
    infra_ok: bool = True
    flag_trigger: str | None = None


class RunDetailOut(EvaluationRunOut):
    tier_results: list[TierResultOut] = []


class GoldenSetManifestIn(BaseModel):
    name: str
    model_class: ModelClass
    version: str
    checksum: str = Field(description="content hash, or 'auto' to compute from data_ref")
    conditions: list[Condition]
    safety_critical: list[str]
    recall_floors: dict[str, float]
    license: str
    is_public: bool
    domain: str = "general"
    data_ref: str = Field(default="", description="local path to the fetched data (gitignored)")
    label_map: dict[str, str] = Field(
        default_factory=dict,
        description="model-emitted label → dataset label (e.g. {'person': 'pedestrian'}), "
        "applied to predictions before scoring (F6)",
    )


class GoldenSetOut(BaseModel):
    id: str
    name: str
    model_class: ModelClass
    version: str
    checksum: str
    conditions: list[Condition]
    safety_critical_classes: list[str]
    recall_floors: dict[str, float]
    reevaluation_flagged: list[str] = []


class GoldenSetStatusOut(BaseModel):
    id: str
    name: str
    model_class: ModelClass
    version: str
    checksum: str
    evaluated_run_ids: list[str] = []
    reevaluation_intents: list[str] = []  # model_version_ids with an open claim


class DecisionIn(BaseModel):
    # FR-013/T026: the reviewer identity is the authenticated principal, never a
    # client-supplied field. A `reviewer` in the body is ignored (extra keys are
    # dropped) so no caller can self-assert who decided.
    decision: Decision
    rationale: str = Field(min_length=1)


class AdjudicationItemOut(BaseModel):
    run_id: str
    trigger: str | None = None
    evidence_ref: str = ""
    model_version_id: str
    model_name: str | None = None
    flagged_at: datetime | None = None
