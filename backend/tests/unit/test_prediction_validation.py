"""T030 (US2): NaN/infinite/malformed prediction score validation."""

from engine.adapters.base import Prediction
from engine.metrics.coverage import compute_coverage, score_issues, shape_issues


def test_mismatched_detection_arrays_are_malformed():
    p = Prediction(image_id="i", boxes=[[0, 0, 1, 1]], scores=[0.9, 0.8], labels=["a"])
    assert any(i["code"] == "malformed_output" for i in shape_issues([p]))


def test_invalid_box_geometry_is_malformed():
    p = Prediction(image_id="i", boxes=[[5, 5, 1, 1]], scores=[0.9], labels=["a"])  # x2<x1
    assert any(i["code"] == "malformed_output" for i in shape_issues([p]))


def test_malformed_detection_makes_coverage_invalid():
    ann = {"i": [{"label": "a", "bbox": [0, 0, 1, 1]}]}
    p = Prediction(image_id="i", boxes=[[0, 0, 1, 1]], scores=[], labels=["a"])  # len mismatch
    cov = compute_coverage([p], ann)
    assert cov.valid is False


def test_nan_probability_flagged():
    p = Prediction(image_id="i", label="cat", class_scores={"cat": float("nan")})
    assert any(i["code"] == "nan_score" for i in score_issues([p]))


def test_inf_detection_score_flagged():
    p = Prediction(image_id="i", boxes=[[0, 0, 1, 1]], scores=[float("inf")], labels=["x"])
    assert any(i["code"] == "nan_score" for i in score_issues([p]))


def test_finite_scores_clean():
    p = Prediction(image_id="i", boxes=[[0, 0, 1, 1]], scores=[0.9], labels=["x"])
    assert score_issues([p]) == []


def test_none_string_score_is_flagged():
    p = Prediction(image_id="i", label="cat", class_scores={"cat": float("-inf")})
    assert any(i["code"] == "nan_score" for i in score_issues([p]))
