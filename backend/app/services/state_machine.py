"""ModelVersion state machine + the FR-012 flag rule (T021, T039).

Encodes Constitution I: the ONLY edge into `approved` from a flagged run passes
through an AdjudicationRecord with decision=approve. There is no transition —
and no helper in this module — that moves a flagged version to `approved`
without a recorded human decision.
"""

from dataclasses import dataclass

from app.db.enums import Decision, ModelStatus, Verdict

# Legal transitions (data-model.md). `approved` from pending_adjudication is
# reachable ONLY via apply_adjudication(), which requires a decision record.
_TRANSITIONS: dict[ModelStatus, set[ModelStatus]] = {
    ModelStatus.pending: {ModelStatus.evaluating},
    ModelStatus.evaluating: {
        ModelStatus.approved,
        ModelStatus.rejected,
        ModelStatus.pending_adjudication,
        ModelStatus.pending,  # infra failure → back to pending (never a model `fail`)
    },
    ModelStatus.pending_adjudication: {ModelStatus.approved, ModelStatus.rejected},
    # golden-set update (FR-004) re-flags for re-evaluation:
    ModelStatus.approved: {ModelStatus.evaluating},
    ModelStatus.rejected: {ModelStatus.evaluating},
}


class IllegalTransition(RuntimeError):
    pass


def assert_transition(current: ModelStatus, new: ModelStatus) -> None:
    if new not in _TRANSITIONS.get(current, set()):
        raise IllegalTransition(f"{current.value} → {new.value} is not a legal transition")


@dataclass(frozen=True)
class FlagInput:
    """Everything the flag rule needs about a completed run (FR-012)."""

    all_thresholds_met: bool
    safety_recall_breach: bool  # (a) safety-critical recall < floor, clean OR any condition
    unratified_threshold: bool  # (b) any applied threshold unset/unratified
    provenance_incomplete: bool  # (c) declared training provenance missing/empty
    infra_ok: bool = True


def flag_trigger(inp: FlagInput) -> str | None:
    """Return the adjudication trigger string, or None when no flag applies."""
    triggers = []
    if inp.safety_recall_breach:
        triggers.append("safety_critical_recall_below_floor")
    if inp.unratified_threshold:
        triggers.append("unratified_threshold")
    if inp.provenance_incomplete:
        triggers.append("incomplete_provenance")
    return "+".join(triggers) if triggers else None


def decide_verdict(inp: FlagInput) -> Verdict:
    """FR-012: flag conditions (a)-(c) → pending_adjudication; other
    below-threshold results auto-reject; all-pass with no flags → pass.

    An infra failure never yields a model verdict of `fail` (edge case):
    the run records infra_ok=false and the version goes back to pending —
    handled by the orchestrator, not here.
    """
    if flag_trigger(inp) is not None:
        return Verdict.pending_adjudication
    return Verdict.passed if inp.all_thresholds_met else Verdict.fail


def status_for_verdict(verdict: Verdict) -> ModelStatus:
    return {
        Verdict.passed: ModelStatus.approved,
        Verdict.fail: ModelStatus.rejected,
        Verdict.pending_adjudication: ModelStatus.pending_adjudication,
    }[verdict]


def apply_adjudication(current: ModelStatus, decision: Decision) -> ModelStatus:
    """The only path out of pending_adjudication (Constitution I). The caller
    MUST have persisted an AdjudicationRecord in the same transaction."""
    if current is not ModelStatus.pending_adjudication:
        raise IllegalTransition("adjudication decision requires status=pending_adjudication")
    if decision is Decision.approve:
        return ModelStatus.approved
    # reject and request_changes both leave the version unapproved; a corrected
    # model comes back as a NEW version (data-model.md).
    return ModelStatus.rejected
