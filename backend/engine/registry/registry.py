"""Model-class → benchmark registry (T013, FR-006, Constitution III).

Every supported class has an entry; Tier 1 refuses a class with no registered
benchmark. Adding a class = adding an entry + a conforming dataset — no engine
change (FR-020/025). Vision-language/document benchmarks are out of scope for
the POC (spec).
"""

from dataclasses import dataclass

from app.db.enums import ModelClass


@dataclass(frozen=True)
class Benchmark:
    """A Tier-1 capability benchmark slot.

    `dataset` names the stand-in dataset directory the harness resolves via
    engine.datasets (fetched by scripts/, never committed); `reference` names
    the real-world benchmark this slot stands in for.
    """

    dataset: str
    metric: str  # key produced by engine.metrics
    reference: str


REGISTRY: dict[ModelClass, Benchmark] = {
    ModelClass.detection: Benchmark(
        dataset="open-images-det-sample", metric="map_50_95", reference="COCO / LVIS mAP"
    ),
    ModelClass.classification: Benchmark(
        dataset="open-images-cls-sample", metric="top1", reference="ImageNet top-1"
    ),
    ModelClass.segmentation: Benchmark(
        dataset="segmentation-sample", metric="miou", reference="Cityscapes mIoU"
    ),
    ModelClass.pose: Benchmark(
        dataset="pose-sample", metric="oks_map", reference="COCO Keypoints"
    ),
    ModelClass.lane: Benchmark(dataset="lane-sample", metric="f1", reference="CULane F1"),
    ModelClass.face: Benchmark(dataset="face-sample", metric="nme", reference="WFLW NME"),
}


class UnknownModelClass(ValueError):
    pass


def get_benchmark(model_class: ModelClass) -> Benchmark:
    try:
        return REGISTRY[model_class]
    except KeyError as e:
        raise UnknownModelClass(
            f"no benchmark registered for model class '{model_class}' (FR-006)"
        ) from e
