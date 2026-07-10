"""T048 — Scenario C: per-condition scores, worst-case drop, per-class recall
for safety-critical classes (FR-008/009/026)."""

import pytest

from tests.conftest import HEALTHY_DET, det_manifest, register_golden, submit_model


def _tier2(client):
    register_golden(client, det_manifest())
    mv = submit_model(client, weights_path=HEALTHY_DET, name="t2", sources=["s"])
    runs = client.get(f"/models/{mv['id']}/history").json()
    run = client.get(f"/runs/{runs[0]['id']}").json()
    return [t for t in run["tier_results"] if t["tier"] == "domain_stress"]


def test_each_condition_scored_separately(client):
    t2 = _tier2(client)
    conditions = [t["condition"] for t in t2]
    assert conditions[0] == "clean"
    assert set(conditions) == {"clean", "rain", "low_light", "fog"}  # one row per condition
    scores = {t["condition"]: t["metrics"]["map_50_95"] for t in t2}
    assert all(v is not None for v in scores.values())
    # perturbations really degrade a brightness-sensitive model
    assert min(scores["rain"], scores["low_light"], scores["fog"]) < scores["clean"]


def test_worst_case_drop_reported(client):
    t2 = _tier2(client)
    clean = next(t for t in t2 if t["condition"] == "clean")
    wcd = clean["metrics"]["worst_case_drop"]
    assert wcd["metric"] == "map_50_95"
    assert wcd["worst_condition"] in ("rain", "low_light", "fog")
    assert wcd["drop"] >= 0
    assert wcd["clean"] - wcd["worst_score"] == pytest.approx(wcd["drop"], abs=1e-6)


def test_per_class_recall_surfaced_for_safety_classes(client):
    t2 = _tier2(client)
    for t in t2:
        sc = t["metrics"]["safety_critical"]
        assert "pedestrian" in sc  # FR-009: never aggregate-only
        row = sc["pedestrian"]
        assert row["recall"] is not None and row["floor"] == 0.6
        assert isinstance(row["ok"], bool)
