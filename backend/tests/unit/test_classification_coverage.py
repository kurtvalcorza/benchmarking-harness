"""T029 (US2): prediction coverage over the expected dataset.

Complete / missing / duplicate / unexpected batches produce the right coverage
accounting and validity flag.
"""

from engine.adapters.base import Prediction
from engine.metrics.coverage import compute_coverage

ANN = {
    "img1": [{"label": "cat"}],
    "img2": [{"label": "dog"}],
    "img3": [{"label": "cat"}],
}


def _p(image_id, label):
    return Prediction(image_id=image_id, label=label, class_scores={label: 0.9})


def test_complete_coverage_is_valid():
    preds = [_p("img1", "cat"), _p("img2", "dog"), _p("img3", "cat")]
    cov = compute_coverage(preds, ANN)
    assert cov.expected_count == 3
    assert cov.scored_count == 3
    assert cov.missing_count == 0
    assert cov.duplicate_count == 0
    assert cov.unexpected_count == 0
    assert cov.valid is True


def test_missing_prediction_is_counted_but_valid():
    preds = [_p("img1", "cat"), _p("img2", "dog")]  # img3 omitted
    cov = compute_coverage(preds, ANN)
    assert cov.expected_count == 3
    assert cov.scored_count == 2
    assert cov.missing_count == 1
    # missing alone does not make the OUTPUT structurally invalid; it lowers score
    assert cov.valid is True
    assert any(i["code"] == "missing_prediction" for i in cov.issues)


def test_duplicate_prediction_is_invalid():
    preds = [_p("img1", "cat"), _p("img1", "cat"), _p("img2", "dog"), _p("img3", "cat")]
    cov = compute_coverage(preds, ANN)
    assert cov.duplicate_count == 1
    assert cov.valid is False


def test_unexpected_prediction_is_invalid():
    preds = [_p("img1", "cat"), _p("img2", "dog"), _p("img3", "cat"), _p("ghost", "cat")]
    cov = compute_coverage(preds, ANN)
    assert cov.unexpected_count == 1
    assert cov.valid is False


def test_nan_score_flagged_invalid():
    p = Prediction(image_id="img1", label="cat", class_scores={"cat": float("nan")})
    preds = [p, _p("img2", "dog"), _p("img3", "cat")]
    cov = compute_coverage(preds, ANN)
    assert cov.valid is False
    assert any(i["code"] == "nan_score" for i in cov.issues)


def test_issue_examples_are_bounded():
    big_ann = {f"i{n}": [{"label": "cat"}] for n in range(100)}
    cov = compute_coverage([], big_ann)  # all missing
    assert cov.missing_count == 100
    assert len(cov.issues) <= 20  # bounded evidence, never the full set
