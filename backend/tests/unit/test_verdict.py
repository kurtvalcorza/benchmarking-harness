"""T024 — verdict vs thresholds (pass / fail / pending), scoring engine level."""

from app.db.enums import Tier, Verdict
from app.services.config import Threshold
from engine.scoring import score_run
from engine.tiers.tier1_capability import TierOutcome, check_threshold


def _outcome(passed, unratified=False, tier=Tier.capability, metrics=None, threshold=None):
    return TierOutcome(
        tier=tier,
        metrics=metrics or {},
        threshold=threshold,
        passed=passed,
        unratified=unratified,
    )


def test_check_threshold_pass_fail_and_pending():
    ratified = Threshold(metric="map_50_95", minimum=0.25, ratified=True)
    assert check_threshold({"map_50_95": 0.30}, ratified) == (
        True,
        {"metric": "map_50_95", "minimum": 0.25, "ratified": True},
        False,
    )
    passed, _, unratified = check_threshold({"map_50_95": 0.10}, ratified)
    assert passed is False and unratified is False

    # unset threshold → pending, never a silent pass (FR-012b)
    assert check_threshold({"map_50_95": 0.99}, None) == (None, None, True)

    # unratified threshold → pending
    unrat = Threshold(metric="map_50_95", minimum=0.25, ratified=False)
    passed, thr, unratified = check_threshold({"map_50_95": 0.99}, unrat)
    assert passed is None and unratified is True and thr["ratified"] is False

    # metric missing from results → pending, not fabricated (Constitution V)
    passed, _, unratified = check_threshold({}, ratified)
    assert passed is None and unratified is True


def test_score_run_all_pass():
    s = score_run(
        outcomes=[_outcome(True), _outcome(True, tier=Tier.domain_stress)],
        safety_breach=False,
        declared_sources=["dataset A"],
    )
    assert s.verdict is Verdict.passed and s.flag_trigger is None


def test_score_run_hard_fail_names_the_metric():
    s = score_run(
        outcomes=[
            _outcome(
                False,
                metrics={"map_50_95": 0.1},
                threshold={"metric": "map_50_95", "minimum": 0.25, "ratified": True},
            )
        ],
        safety_breach=False,
        declared_sources=["dataset A"],
    )
    assert s.verdict is Verdict.fail
    assert s.failing and "map_50_95" in s.failing[0]  # SC-009: reason is recorded


def test_score_run_empty_provenance_flags():
    s = score_run(outcomes=[_outcome(True)], safety_breach=False, declared_sources=["  "])
    assert s.verdict is Verdict.pending_adjudication
    assert "incomplete_provenance" in s.flag_trigger


def test_score_run_safety_breach_flags():
    s = score_run(outcomes=[_outcome(True)], safety_breach=True, declared_sources=["a"])
    assert s.verdict is Verdict.pending_adjudication


def test_score_run_unratified_flags():
    s = score_run(
        outcomes=[_outcome(None, unratified=True)], safety_breach=False, declared_sources=["a"]
    )
    assert s.verdict is Verdict.pending_adjudication
