"""Pydantic response/request schemas mirroring contracts/openapi.yaml."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.db.enums import Condition, Decision, ModelClass, ModelStatus, Tier, Verdict


class ModelVersionOut(BaseModel):
    id: str
    model_id: str
    name: str
    model_class: ModelClass
    version: str
    framework: str
    status: ModelStatus
    submitted_at: datetime


class ModelDetailOut(ModelVersionOut):
    declared_sources: list[str] = []
    card_markdown: str | None = None
    missing_card_fields: list[str] = []


class TierResultOut(BaseModel):
    tier: Tier
    condition: Condition | None = None
    metrics: dict
    threshold: dict | None = None
    passed: bool | None = None
    evidence_ref: str = ""
    dataset_checksum: str = ""


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


class DecisionIn(BaseModel):
    reviewer: str = Field(min_length=1)
    decision: Decision
    rationale: str = Field(min_length=1)


class AdjudicationItemOut(BaseModel):
    run_id: str
    trigger: str | None = None
    evidence_ref: str = ""
    model_version_id: str
    model_name: str | None = None
    flagged_at: datetime | None = None
