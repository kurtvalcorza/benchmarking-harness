"""Abandoned upload janitor (T043, US3).

Interrupted or crashed uploads leave `.part` files in the staging directory.
This sweep removes ones older than a threshold. It is root-contained: it only
touches `*.part` files directly under the configured staging dir, never the
finalized artifacts.

Run periodically (cron/systemd timer) or on demand:
    python -m app.services.artifact_janitor --older-than 3600
"""

from __future__ import annotations

import argparse
import time

from app.services.artifact_ingest import staging_dir
from app.services.config import AppConfig, load_config


def sweep_abandoned(
    cfg: AppConfig, older_than_seconds: float, now: float | None = None
) -> int:
    """Remove staged `.part` files older than `older_than_seconds`. Returns the
    count removed. `now` may be injected for deterministic tests."""
    now = time.time() if now is None else now
    staging = staging_dir(cfg)
    if not staging.exists():
        return 0
    removed = 0
    for p in staging.glob("*.part"):
        try:
            if now - p.stat().st_mtime >= older_than_seconds:
                p.unlink(missing_ok=True)
                removed += 1
        except OSError:
            continue
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description="Sweep abandoned upload .part files")
    parser.add_argument(
        "--older-than", type=float, default=3600.0, help="age threshold in seconds"
    )
    args = parser.parse_args()
    removed = sweep_abandoned(load_config(), args.older_than)
    print(f"removed {removed} abandoned .part file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
