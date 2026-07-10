"""T019 — Constitution I gate: no auto-approval path exists for flagged runs.

Written FAIL-FIRST against the state machine + API surface: a flagged run can
only reach `approved` through a recorded human decision.
"""

import pytest

from app.db.enums import Decision, ModelStatus, Verdict
from app.services.state_machine import (
    FlagInput,
    IllegalTransition,
    apply_adjudication,
    decide_verdict,
    status_for_verdict,
)


def test_flagged_run_never_maps_to_approved():
    """Any flag condition → pending_adjudication, even when every threshold passes."""
    for flags in (
        {"safety_recall_breach": True},
        {"unratified_threshold": True},
        {"provenance_incomplete": True},
        {"safety_recall_breach": True, "provenance_incomplete": True},
    ):
        base = dict(
            all_thresholds_met=True,
            safety_recall_breach=False,
            unratified_threshold=False,
            provenance_incomplete=False,
        )
        base.update(flags)
        inp = FlagInput(**base)
        verdict = decide_verdict(inp)
        assert verdict is Verdict.pending_adjudication
        assert status_for_verdict(verdict) is ModelStatus.pending_adjudication


def test_adjudication_is_the_only_exit_from_pending():
    # approve requires a decision; the helper refuses any other starting state
    assert apply_adjudication(ModelStatus.pending_adjudication, Decision.approve) is ModelStatus.approved
    for status in (ModelStatus.pending, ModelStatus.evaluating, ModelStatus.approved, ModelStatus.rejected):
        with pytest.raises(IllegalTransition):
            apply_adjudication(status, Decision.approve)


def test_reject_and_request_changes_never_approve():
    assert apply_adjudication(ModelStatus.pending_adjudication, Decision.reject) is ModelStatus.rejected
    assert (
        apply_adjudication(ModelStatus.pending_adjudication, Decision.request_changes)
        is not ModelStatus.approved
    )


def test_api_exposes_no_force_approve_route(client):
    """The ONLY route that can move a flagged model forward is the decision
    endpoint (openapi contract). No PUT/PATCH on models, no /approve route."""
    spec = client.get("/openapi.json").json()
    mutating = {
        (path, method.upper())
        for path, ops in spec["paths"].items()
        for method in ops
        if method.upper() in {"POST", "PUT", "PATCH", "DELETE"}
    }
    allowed = {
        ("/models", "POST"),
        ("/golden-sets", "POST"),
        ("/adjudication/{run_id}/decision", "POST"),
    }
    assert mutating == allowed, f"unexpected mutating routes: {mutating - allowed}"


def test_decision_on_unflagged_run_is_409(client):
    from tests.conftest import HEALTHY_DET, det_manifest, register_golden, submit_model

    register_golden(client, det_manifest())
    mv = submit_model(client, weights_path=HEALTHY_DET, name="clean-pass", sources=["synthetic v1"])
    runs = client.get(f"/models/{mv['id']}/history").json()
    assert runs, "expected an auto-triggered run"
    r = client.post(
        f"/adjudication/{runs[-1]['id']}/decision",
        json={"reviewer": "r", "decision": "approve", "rationale": "n/a"},
    )
    assert r.status_code == 409
