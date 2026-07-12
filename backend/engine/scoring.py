"""Scoring engine + verdict assignment (T030, FR-011/012).

Folds tier outcomes + provenance into the FR-012 flag rule:
  (a) safety-critical recall below floor (clean or any condition) → flag
  (b) any applied threshold unset/unratified                      → flag
  (c) declared provenance incomplete                              → flag
Flags → pending_adjudication; other below-threshold → fail; else pass.
"""

from dataclasses import dataclass

from app.db.enums import Verdict
from app.services.state_machine import FlagInput, decide_verdict, flag_trigger
from engine.tiers.tier1_capability import TierOutcome


@dataclass
class RunScore:
    verdict: Verdict
    flag_trigger: str | None
    failing: list[str]  # human-readable per-tier failure reasons (SC-009)


def provenance_incomplete(declared_sources: list[str]) -> bool:
    return not [s for s in declared_sources if s and s.strip()]


def score_run(
    *,
    outcomes: list[TierOutcome],
    safety_breach: bool,
    declared_sources: list[str],
    safety_metric: str = "recall",
) -> RunScore:
    failing = []
    for o in outcomes:
        if o.passed is False:
            thr = o.threshold or {}
            cond = f" [{o.condition}]" if o.condition else ""
            failing.append(
                f"{o.tier.value}{cond}: {thr.get('metric')}="
                f"{o.metrics.get(thr.get('metric'))} < {thr.get('minimum')}"
            )
    inp = FlagInput(
        all_thresholds_met=all(o.passed is True for o in outcomes) and bool(outcomes),
        safety_recall_breach=safety_breach,
        unratified_threshold=any(o.unratified for o in outcomes),
        provenance_incomplete=provenance_incomplete(declared_sources),
        safety_metric=safety_metric,
    )
    return RunScore(
        verdict=decide_verdict(inp),
        flag_trigger=flag_trigger(inp),
        failing=failing,
    )
