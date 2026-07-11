"""F6 — label canonicalization: model-emitted labels map onto the dataset's
label space before scoring; unmapped labels pass through untouched."""

import pytest

from engine.adapters.base import Prediction
from engine.metrics import canonicalize, evaluate_detection


def _pred(**kw) -> Prediction:
    base = dict(image_id="img_000", boxes=[[0, 0, 10, 10]], scores=[0.9], labels=["person"])
    base.update(kw)
    return Prediction(**base)


def test_detection_labels_mapped():
    out = canonicalize([_pred()], {"person": "pedestrian"})
    assert out[0].labels == ["pedestrian"]


def test_unmapped_labels_pass_through():
    out = canonicalize([_pred(labels=["bicycle"])], {"person": "pedestrian"})
    assert out[0].labels == ["bicycle"]


def test_empty_map_is_identity():
    p = _pred()
    assert canonicalize([p], {}) is not None
    assert canonicalize([p], {})[0].labels == p.labels


def test_classification_label_and_scores_mapped():
    p = Prediction(image_id="x", label="car", class_scores={"car": 0.8, "cat": 0.2})
    out = canonicalize([p], {"car": "vehicle"})
    assert out[0].label == "vehicle"
    assert out[0].class_scores == {"vehicle": 0.8, "cat": 0.2}


def test_colliding_class_scores_are_summed_not_overwritten():
    """car/truck/bus → vehicle must combine probabilities, not keep the last."""
    p = Prediction(
        image_id="x",
        label="car",
        class_scores={"car": 0.5, "truck": 0.3, "bus": 0.1, "cat": 0.1},
    )
    out = canonicalize([p], {"car": "vehicle", "truck": "vehicle", "bus": "vehicle"})
    assert out[0].class_scores["vehicle"] == pytest.approx(0.9)
    assert out[0].class_scores["cat"] == pytest.approx(0.1)


def test_mapping_repairs_scoring():
    """The concrete F6 failure: correct boxes, foreign vocabulary → mAP 0;
    the same predictions score once canonicalized."""
    annotations = {"img_000": [{"label": "pedestrian", "bbox": [0, 0, 10, 10]}]}
    raw = [_pred()]
    assert evaluate_detection(raw, annotations)["map_50_95"] == 0.0
    mapped = canonicalize(raw, {"person": "pedestrian"})
    assert evaluate_detection(mapped, annotations)["map_50_95"] > 0.9
