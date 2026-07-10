#!/usr/bin/env python3
"""Register a Golden Test Set with the harness (POST /golden-sets, FR-020/026).

    python scripts/register_golden_set.py --class detection
    python scripts/register_golden_set.py --class classification --api http://localhost:8000

By default registers the committed owned sample golden set for the class
(safety-critical classes + recall floors included in the manifest). Point
--data at any conforming dataset directory to register real fetched data.
"""

import argparse
import json
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

DEFAULTS = {
    "detection": {
        "name": "det-golden",
        "data": REPO / "samples" / "golden" / "det-golden",
        "safety_critical": ["pedestrian"],
        "recall_floors": {"pedestrian": 0.6},
    },
    "classification": {
        "name": "cls-golden",
        "data": REPO / "samples" / "golden" / "cls-golden",
        "safety_critical": ["animal"],
        "recall_floors": {"animal": 0.6},
    },
}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--class", dest="model_class", choices=list(DEFAULTS), required=True)
    p.add_argument("--api", default="http://localhost:8000")
    p.add_argument("--data", help="path to a conforming dataset dir (default: owned sample)")
    p.add_argument("--version", default="v1")
    args = p.parse_args()

    cfg = DEFAULTS[args.model_class]
    manifest = {
        "name": cfg["name"],
        "model_class": args.model_class,
        "version": args.version,
        "checksum": "auto",
        "conditions": ["rain", "low_light", "fog"],
        "safety_critical": cfg["safety_critical"],
        "recall_floors": cfg["recall_floors"],
        "license": "owned",
        "is_public": False,
        "domain": "local-context-demo",
        "data_ref": str(Path(args.data).resolve() if args.data else cfg["data"]),
    }
    req = urllib.request.Request(
        f"{args.api}/golden-sets",
        data=json.dumps(manifest).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        body = json.loads(resp.read())
    print(json.dumps(body, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
