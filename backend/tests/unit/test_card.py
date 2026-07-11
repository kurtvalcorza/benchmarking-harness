"""T044 — Model Card: preserves human sections, marks missing as `to be confirmed`."""

from datetime import UTC, datetime

from engine.cards.generator import TBC, CardInputs, generate, split_human_sections


def _inputs(**kw) -> CardInputs:
    base = dict(
        model_name="demo-detector",
        verdict="pass",
        evaluated_at=datetime(2026, 7, 10, tzinfo=UTC),
        harness_version="0.1.0",
        sandbox_mode="docker",
        golden_set={"name": "det-golden", "version": "v1", "checksum": "abc123"},
        tier_results=[
            {
                "tier": "capability",
                "condition": None,
                "metrics": {"map_50_95": 0.41},
                "threshold": {"metric": "map_50_95", "minimum": 0.25, "ratified": True},
                "passed": True,
            }
        ],
        framework="stub",
        declared_sources=["synthetic set v1"],
        artifact_digest="deadbeef",
    )
    base.update(kw)
    return CardInputs(**base)


def test_missing_fields_render_tbc_never_blank():
    card, missing = generate(
        _inputs(verdict=None, golden_set=None, declared_sources=[], artifact_digest=None)
    )
    assert TBC in card
    assert "verdict" in missing
    assert "declared_sources" in missing
    assert "golden_set.checksum" in missing
    # no template slot collapsed to empty: every '- **' line has content after ':'
    for line in card.splitlines():
        if line.startswith("- **") and line.endswith(":"):
            raise AssertionError(f"blank field rendered: {line!r}")


def test_populated_card_has_machine_blocks():
    card, missing = generate(_inputs())
    assert "## Benchmark Results" in card
    assert "map_50_95" in card and "0.41" in card
    assert "## Provenance" in card and "synthetic set v1" in card
    assert "## Adjudication" in card
    assert "verdict" not in missing


def test_human_sections_preserved_across_regeneration():
    card1, _ = generate(_inputs())
    edited = card1.replace(
        "to be confirmed", "Hand-written intended-use statement.", 1
    )
    card2, _ = generate(_inputs(verdict="fail"), existing_card=edited)
    assert "Hand-written intended-use statement." in card2  # FR-014
    assert card2.count("## Benchmark Results") == 1  # machine block replaced, not appended
    assert "- **Verdict**: fail" in card2


def test_pending_adjudication_never_reads_as_no_review_needed():
    """A flagged, undecided run must show PENDING — claiming 'no adjudication
    required' would be misleading compliance evidence."""
    card, _ = generate(
        _inputs(
            verdict="pending_adjudication",
            flag_trigger="safety_critical_recall_below_floor",
            adjudications=[],
        )
    )
    assert "No adjudication required" not in card
    assert "PENDING human adjudication" in card
    assert "safety_critical_recall_below_floor" in card


def test_adjudication_block_lists_decisions():
    card, _ = generate(
        _inputs(
            adjudications=[
                {
                    "decision": "reject",
                    "reviewer": "adjudicator@example.com",
                    "rationale": "pedestrian recall collapsed in low light",
                    "decided_at": "2026-07-10T12:00:00+00:00",
                    "trigger": "safety_critical_recall_below_floor",
                }
            ]
        )
    )
    assert "reject" in card and "adjudicator@example.com" in card
    assert "pedestrian recall collapsed" in card


def test_split_human_sections_roundtrip():
    card, _ = generate(_inputs())
    human = split_human_sections(card)
    assert "## Benchmark Results" not in human
    assert human.strip().startswith("# Model Card: demo-detector")
