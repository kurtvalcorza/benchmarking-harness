"""Core enums (data-model.md)."""

from enum import Enum


class ModelClass(str, Enum):
    detection = "detection"
    segmentation = "segmentation"
    classification = "classification"
    pose = "pose"
    lane = "lane"
    face = "face"


class Tier(str, Enum):
    capability = "capability"
    domain_stress = "domain_stress"
    operational_safety = "operational_safety"


class Verdict(str, Enum):
    passed = "pass"
    fail = "fail"
    pending_adjudication = "pending_adjudication"


class ModelStatus(str, Enum):
    pending = "pending"
    evaluating = "evaluating"
    pending_adjudication = "pending_adjudication"
    approved = "approved"
    rejected = "rejected"


class Condition(str, Enum):
    clean = "clean"
    rain = "rain"
    low_light = "low_light"
    fog = "fog"


class Decision(str, Enum):
    approve = "approve"
    reject = "reject"
    request_changes = "request_changes"


class Role(str, Enum):
    """Authorization roles (security-boundary.md). A principal may hold several."""

    submitter = "submitter"
    governance = "governance"
    adjudicator = "adjudicator"
    auditor = "auditor"


class JobKind(str, Enum):
    evaluate_model_version = "evaluate_model_version"


class JobReason(str, Enum):
    submission = "submission"
    golden_set_update = "golden_set_update"
    mid_run_staleness = "mid_run_staleness"
    operator_retry = "operator_retry"


class JobState(str, Enum):
    pending = "pending"
    dispatching = "dispatching"
    dispatched = "dispatched"
    claimed = "claimed"
    completed = "completed"
    failed = "failed"


class JobOutcome(str, Enum):
    claimed = "claimed"
    duplicate = "duplicate"
    completed = "completed"
    retryable_failure = "retryable_failure"
    terminal_failure = "terminal_failure"


class GroundingStatus(str, Enum):
    measured = "measured"
    unavailable = "unavailable"


TIER_ORDER: list[Tier] = [Tier.capability, Tier.domain_stress, Tier.operational_safety]
