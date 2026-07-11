"""T038 (US2): omitting predictions cannot improve a verdict.

The classification scorer accounts for every expected item, so dropping a
correctly-classified example can only lower — never raise — the score, and
dropping a hard example cannot inflate it. This is the anti-inflation guarantee.
"""

from engine.adapters.base import Prediction
from engine.metrics.classification import evaluate_classification

ANN = {f"img{n}": [{"label": "cat" if n % 2 == 0 else "dog"}] for n in range(10)}


def _correct(image_id, label):
    return Prediction(image_id=image_id, label=label, class_scores={label: 0.99})


def test_omitting_a_correct_prediction_lowers_top1():
    full = [_correct(i, ann[0]["label"]) for i, ann in ANN.items()]
    complete = evaluate_classification(full, ANN)
    assert complete["top1"] == 1.0
    assert complete["num_images"] == 10

    # drop one correct prediction: denominator stays 10, so top1 drops
    partial = evaluate_classification(full[:-1], ANN)
    assert partial["num_images"] == 10
    assert partial["top1"] < complete["top1"]


def test_omitting_a_wrong_prediction_cannot_raise_score():
    # 9 correct + 1 wrong
    preds = [_correct(i, ANN[i][0]["label"]) for i in list(ANN)[:-1]]
    preds.append(Prediction(image_id="img9", label="cat", class_scores={"cat": 0.99}))  # wrong (dog)
    with_wrong = evaluate_classification(preds, ANN)

    # omit the wrong one: the expected item is still counted (missing→incorrect),
    # so the score cannot go UP by hiding the failure
    without_wrong = evaluate_classification(preds[:-1], ANN)
    assert without_wrong["top1"] <= with_wrong["top1"]
    assert without_wrong["num_images"] == 10
