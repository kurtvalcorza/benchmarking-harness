"""T068 [C1] — the FR-012 flag rule, exhaustively.

(a) safety-critical recall < floor  → pending_adjudication
(b) unratified/unset threshold      → pending_adjudication
(c) incomplete provenance           → pending_adjudication
none of (a)-(c) + below threshold   → fail (auto-reject)
none of (a)-(c) + all pass          → pass
"""

import pytest

from app.db.enums import Verdict
from app.services.state_machine import FlagInput, decide_verdict, flag_trigger


def _inp(**kw) -> FlagInput:
    base = dict(
        all_thresholds_met=True,
        safety_recall_breach=False,
        unratified_threshold=False,
        provenance_incomplete=False,
    )
    base.update(kw)
    return FlagInput(**base)


def test_all_pass_no_flags_is_pass():
    assert decide_verdict(_inp()) is Verdict.passed
    assert flag_trigger(_inp()) is None


def test_below_threshold_without_flags_auto_rejects():
    assert decide_verdict(_inp(all_thresholds_met=False)) is Verdict.fail


@pytest.mark.parametrize(
    "kw,expected_trigger",
    [
        ({"safety_recall_breach": True}, "safety_critical_recall_below_floor"),
        ({"unratified_threshold": True}, "unratified_threshold"),
        ({"provenance_incomplete": True}, "incomplete_provenance"),
    ],
)
def test_each_flag_routes_to_adjudication(kw, expected_trigger):
    # flags dominate regardless of threshold outcome (a human decides, not the gate)
    for met in (True, False):
        inp = _inp(all_thresholds_met=met, **kw)
        assert decide_verdict(inp) is Verdict.pending_adjudication
        assert expected_trigger in flag_trigger(inp)


def test_combined_flags_concatenate_triggers():
    inp = _inp(safety_recall_breach=True, provenance_incomplete=True)
    trig = flag_trigger(inp)
    assert "safety_critical_recall_below_floor" in trig
    assert "incomplete_provenance" in trig
    assert decide_verdict(inp) is Verdict.pending_adjudication


def test_safety_breach_is_flagged_not_auto_rejected():
    """Spec edge case: a safety-critical floor breach is a HUMAN decision,
    never an automatic fail."""
    assert decide_verdict(_inp(safety_recall_breach=True, all_thresholds_met=False)) is (
        Verdict.pending_adjudication
    )
