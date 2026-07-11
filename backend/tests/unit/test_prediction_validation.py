"""T030 (US2): NaN/infinite/malformed prediction score validation."""

from engine.adapters.base import Prediction
from engine.metrics.coverage import score_issues


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
