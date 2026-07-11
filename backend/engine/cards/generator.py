"""Model Card generator (T045/T046, FR-014/015, Constitution V).

Two-author document: human-owned qualitative sections are PRESERVED verbatim
across regenerations; machine blocks (Benchmark Results / Provenance /
Adjudication) are rebuilt from stored results each run. Any missing or
unverifiable field renders as `to be confirmed` — never blank, never invented.
"""

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

TBC = "to be confirmed"
_MACHINE_BEGIN = "<!-- machine-generated:begin"

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=False,
    trim_blocks=False,
)

DEFAULT_HUMAN_SECTIONS = """# Model Card: {name}

## Intended use

to be confirmed

## Training data description (author-provided)

to be confirmed

## Ethical considerations

to be confirmed
"""


@dataclass
class CardInputs:
    model_name: str
    verdict: str | None
    evaluated_at: datetime | None
    harness_version: str
    sandbox_mode: str | None
    golden_set: dict | None  # {name, version, checksum}
    tier_results: list[dict]  # rows: tier, condition, metrics, threshold, passed
    framework: str | None
    declared_sources: list[str] = field(default_factory=list)
    artifact_digest: str | None = None
    adjudications: list[dict] = field(default_factory=list)  # reviewer/decision/rationale/at
    limitations: list[str] = field(default_factory=list)
    flag_trigger: str | None = None  # why the run awaits adjudication, if it does


def split_human_sections(existing_card: str) -> str:
    """Everything above the machine block is human-owned and preserved."""
    idx = existing_card.find(_MACHINE_BEGIN)
    return (existing_card[:idx] if idx >= 0 else existing_card).rstrip() + "\n"


def _tbc(value) -> str:
    if value is None or value == "" or value == []:
        return TBC
    return str(value)


def generate(inputs: CardInputs, existing_card: str | None = None) -> tuple[str, list[str]]:
    """Render the card. Returns (markdown, missing_fields)."""
    missing: list[str] = []

    def track(name: str, value):
        if value is None or value == "" or value == []:
            missing.append(name)
            return TBC
        return value

    human = (
        split_human_sections(existing_card)
        if existing_card
        else DEFAULT_HUMAN_SECTIONS.format(name=inputs.model_name)
    )

    tier_rows = []
    safety_rows = []
    worst_case_drop = None
    for tr in inputs.tier_results:
        thr = tr.get("threshold") or {}
        metric_key = thr.get("metric") or _primary_metric(tr.get("metrics") or {})
        score = (tr.get("metrics") or {}).get(metric_key)
        passed = tr.get("passed")
        tier_rows.append(
            {
                "tier": tr.get("tier", TBC),
                "condition": tr.get("condition") or "—",
                "metric": _tbc(metric_key),
                "score": _tbc(score),
                "threshold": f"≥ {thr['minimum']}" if thr.get("minimum") is not None else TBC,
                "result": {True: "pass", False: "FAIL"}.get(passed, "pending"),
            }
        )
        sc = (tr.get("metrics") or {}).get("safety_critical") or {}
        for cls, row in sc.items():
            safety_rows.append(
                {
                    "cls": cls,
                    "condition": tr.get("condition") or "—",
                    "recall": _tbc(row.get("recall")),
                    "floor": _tbc(row.get("floor")),
                    "ok": "yes" if row.get("ok") else "**NO**",
                }
            )
        wcd = (tr.get("metrics") or {}).get("worst_case_drop")
        if wcd:
            worst_case_drop = wcd

    limitations = list(inputs.limitations)
    for row in safety_rows:
        if row["ok"] != "yes":
            limitations.append(
                f"Safety-critical class `{row['cls']}` under `{row['condition']}`: "
                f"recall {row['recall']} vs floor {row['floor']}."
            )
    if not limitations:
        limitations = [TBC]

    if inputs.adjudications:
        adj_lines = [
            f"- **{a.get('decision', TBC)}** by {a.get('reviewer', TBC)} at "
            f"{a.get('decided_at', TBC)} — {a.get('rationale', TBC)} "
            f"(trigger: {a.get('trigger', TBC)})"
            for a in inputs.adjudications
        ]
        adjudication_block = "\n".join(adj_lines)
    elif inputs.verdict == "pending_adjudication":
        # never claim "no adjudication required" while the run is BLOCKED on one
        adjudication_block = (
            f"⏳ **PENDING human adjudication** — trigger: {inputs.flag_trigger or TBC}. "
            "This model is not approved; a recorded reviewer decision is required "
            "(Constitution I)."
        )
    else:
        adjudication_block = "No adjudication required for this run."

    gs = inputs.golden_set or {}
    card = _env.get_template("model_card.md.j2").render(
        human_sections=human.rstrip(),
        verdict=track("verdict", inputs.verdict),
        evaluated_at=track(
            "evaluated_at",
            inputs.evaluated_at.isoformat() if inputs.evaluated_at else None,
        ),
        harness_version=inputs.harness_version,
        sandbox_mode=track("sandbox_mode", inputs.sandbox_mode),
        golden_set_name=track("golden_set.name", gs.get("name")),
        golden_set_version=track("golden_set.version", gs.get("version")),
        golden_set_checksum=track("golden_set.checksum", gs.get("checksum")),
        tier_rows=tier_rows,
        safety_rows=safety_rows,
        worst_case_drop=worst_case_drop,
        limitations=limitations,
        framework=track("framework", inputs.framework),
        declared_sources=(
            ", ".join(inputs.declared_sources)
            if [s for s in inputs.declared_sources if s.strip()]
            else track("declared_sources", None)
        ),
        artifact_digest=track("artifact_digest", inputs.artifact_digest),
        adjudication_block=adjudication_block,
    )
    return card, missing


def _primary_metric(metrics: dict) -> str | None:
    for key in ("coco_ap_50_95", "map_50_95", "top1", "grounding_score", "miou", "f1"):
        if key in metrics:
            return key
    return next(iter(metrics), None)


def artifact_digest(path: str) -> str | None:
    p = Path(path)
    if not p.exists():
        return None
    h = hashlib.sha256()
    with p.open("rb") as f:  # stream: real weights can be hundreds of MB
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()[:16]
