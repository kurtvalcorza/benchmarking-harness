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


TIER_ORDER: list[Tier] = [Tier.capability, Tier.domain_stress, Tier.operational_safety]
