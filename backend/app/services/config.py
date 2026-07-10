"""Threshold configuration (T010).

Thresholds live in thresholds.yaml, keyed by model class and tier. A threshold
entry carries `ratified: true|false`; an unset or unratified threshold forces
`pending_adjudication` (spec edge case, FR-012b) — never a silent pass.
"""

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from app.db.enums import ModelClass, Tier

DEFAULT_THRESHOLDS_PATH = Path(__file__).resolve().parents[2] / "thresholds.yaml"


@dataclass(frozen=True)
class Threshold:
    metric: str
    minimum: float
    ratified: bool


def thresholds_path() -> Path:
    return Path(os.environ.get("HARNESS_THRESHOLDS", DEFAULT_THRESHOLDS_PATH))


@lru_cache(maxsize=8)
def _load(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text()) or {}


def get_threshold(model_class: ModelClass, tier: Tier) -> Threshold | None:
    """Return the configured threshold, or None when unset (→ pending_adjudication)."""
    raw = _load(str(thresholds_path())).get(model_class.value, {}).get(tier.value)
    if not raw or "metric" not in raw or "minimum" not in raw:
        return None
    return Threshold(
        metric=raw["metric"],
        minimum=float(raw["minimum"]),
        ratified=bool(raw.get("ratified", False)),
    )


def clear_cache() -> None:
    _load.cache_clear()
