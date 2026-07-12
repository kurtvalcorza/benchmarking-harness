"""InferenceAdapter contract (contracts/inference-adapter.md, T012).

The engine depends only on this interface. Adding a framework = a new adapter;
adding a model class = a registry entry. Adapters MUST NOT access the network
(enforced at runtime by the no-egress sandbox) and MUST be deterministic for
the same weights + images + seed.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from app.db.enums import ModelClass


class AdapterError(RuntimeError):
    """Load/predict failure → run marked infra_ok=false, NOT a model `fail`."""


@dataclass
class Image:
    """A dataset image handed to an adapter. Read-only by contract."""

    id: str
    path: str


@dataclass
class Prediction:
    """Class-appropriate prediction (see contract table).

    detection:      boxes[[x1,y1,x2,y2]], scores[], labels[]
    classification: label, scores[]  (scores = per-class probabilities)
    segmentation:   mask; pose: keypoints; lane: lanes; face: landmarks
    """

    image_id: str
    boxes: list[list[float]] = field(default_factory=list)
    scores: list[float] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    label: str | None = None
    class_scores: dict[str, float] = field(default_factory=dict)
    # US4/segmentation: per-instance predicted masks — one entry per emitted
    # instance: {"label": str, "score": float, "rle": {"size": [h, w],
    # "counts": str}} (COCO RLE). Empty for non-segmentation predictions; the
    # segmentation scorer reduces these to per-class semantic masks (FR-201).
    masks: list[dict[str, Any]] = field(default_factory=list)
    # US5/T062: reproducible per-detection grounding attribution — one entry per
    # emitted localization claim: {"label", "point": [x, y]} (pointing game) or
    # {"label", "energy_inside": float} (attribution-map energy). This is the
    # ONLY channel the Tier 3 grounding evaluator reads; a bare confidence scalar
    # here is ignored (metric-evidence.md §Forbidden substitutions).
    attribution: list[dict[str, Any]] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "image_id": self.image_id,
            "boxes": self.boxes,
            "scores": self.scores,
            "labels": self.labels,
            "label": self.label,
            "class_scores": self.class_scores,
            "masks": self.masks,
            "attribution": self.attribution,
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Prediction":
        return cls(
            image_id=d["image_id"],
            boxes=d.get("boxes") or [],
            scores=d.get("scores") or [],
            labels=d.get("labels") or [],
            label=d.get("label"),
            class_scores=d.get("class_scores") or {},
            masks=d.get("masks") or [],
            attribution=d.get("attribution") or [],
            extra=d.get("extra") or {},
        )


@dataclass
class ModelDescriptor:
    """Feeds the Tier 3 resource profile + provenance (contract: describe())."""

    framework: str
    framework_version: str
    param_count: int | None = None
    input_spec: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "framework": self.framework,
            "framework_version": self.framework_version,
            "param_count": self.param_count,
            "input_spec": self.input_spec,
            "extra": self.extra,
        }


@runtime_checkable
class InferenceAdapter(Protocol):
    def load(self, artifact_ref: str, model_class: ModelClass) -> Any:
        """Load serialized weights into an in-memory model. MUST NOT access the network."""
        ...

    def predict(self, model: Any, images: Iterable[Image]) -> list[Prediction]:
        """Run inference; deterministic for same weights+images+seed."""
        ...

    def describe(self, model: Any) -> ModelDescriptor:
        """Param count, input spec, framework/version."""
        ...


def get_adapter(framework: str) -> InferenceAdapter:
    """Resolve a framework name to its adapter. Heavy adapters import lazily so
    the harness (gating logic, API, stub runs) works without ML extras."""
    fw = framework.lower()
    if fw == "stub":
        from engine.adapters.stub_adapter import StubAdapter

        return StubAdapter()
    if fw == "pytorch":
        from engine.adapters.pytorch_adapter import PyTorchAdapter

        return PyTorchAdapter()
    if fw == "onnx":
        from engine.adapters.onnx_adapter import OnnxAdapter

        return OnnxAdapter()
    raise AdapterError(f"no inference adapter registered for framework '{framework}'")


SUPPORTED_FRAMEWORKS = ("pytorch", "onnx", "stub")
