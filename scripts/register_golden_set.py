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
sys.path.insert(0, str(REPO / "backend"))


def _governance_token() -> str:
    """Mint a local dev governance token (registration requires governance).
    Requires dev auth; pass --token for a real OIDC deployment."""
    from app.services.auth import mint_dev_token
    from app.services.config import load_config

    cfg = load_config()
    if not cfg.dev_auth_enabled:
        raise SystemExit(
            "register_golden_set needs dev auth (HARNESS_AUTH_MODE=dev, non-production) "
            "or an explicit --token; /golden-sets requires a governance bearer token."
        )
    return mint_dev_token("registrar", ["governance"], cfg=cfg)

DEFAULTS = {
    "detection": {
        "name": "det-golden",
        "data": REPO / "samples" / "golden" / "det-golden",
        "safety_critical": ["pedestrian"],
        "recall_floors": {"pedestrian": 0.6},
        # F6: COCO-vocabulary detectors score against the canonical labels
        "label_map": {
            "person": "pedestrian",
            "car": "vehicle",
            "truck": "vehicle",
            "bus": "vehicle",
            "stop sign": "traffic_sign",
            "traffic light": "traffic_sign",
        },
    },
    "classification": {
        "name": "cls-golden",
        "data": REPO / "samples" / "golden" / "cls-golden",
        "safety_critical": ["animal"],
        "recall_floors": {"animal": 0.6},
        "label_map": {},
    },
    "segmentation": {
        "name": "seg-golden",
        "data": REPO / "samples" / "golden" / "seg-golden",
        "safety_critical": ["pedestrian"],
        # segmentation declares per-class IoU floors, not recall floors (FR-214)
        "iou_floors": {"pedestrian": 0.4},
        # F6: a COCO-vocabulary -seg model scores against the canonical labels
        "label_map": {
            "person": "pedestrian",
            "car": "vehicle",
            "truck": "vehicle",
            "bus": "vehicle",
            "stop sign": "traffic_sign",
            "traffic light": "traffic_sign",
        },
    },
}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--class", dest="model_class", choices=list(DEFAULTS), required=True)
    p.add_argument("--api", default="http://localhost:8000")
    p.add_argument(
        "--data",
        help="dataset dir AS SEEN BY THE API/WORKER (with docker compose that is a "
        "container path, e.g. /srv/data/benchmarks/open-images-det-sample or "
        "/srv/samples/golden/det-golden). Default: the owned sample at its local path.",
    )
    p.add_argument(
        "--license",
        dest="license_",
        default=None,
        help="dataset license; REQUIRED with --data (e.g. cc-by-4.0 for Open Images). "
        "The built-in synthetic samples are 'owned'.",
    )
    p.add_argument("--version", default="v1")
    p.add_argument("--token", default=None, help="governance bearer token (default: minted dev token)")
    args = p.parse_args()

    if args.data and not args.license_:
        p.error(
            "--license is required when registering non-sample data — record the REAL "
            "license of the fetched dataset (Constitution II), e.g. --license cc-by-4.0"
        )

    cfg = DEFAULTS[args.model_class]
    manifest = {
        "name": cfg["name"],
        "model_class": args.model_class,
        "version": args.version,
        "checksum": "auto",
        "conditions": ["rain", "low_light", "fog"],
        "safety_critical": cfg["safety_critical"],
        "recall_floors": cfg.get("recall_floors", {}),
        "iou_floors": cfg.get("iou_floors", {}),
        "license": args.license_ or "owned",
        "is_public": False,
        "domain": "local-context-demo",
        "data_ref": args.data if args.data else str(cfg["data"]),
        "label_map": cfg["label_map"],
    }
    token = args.token or _governance_token()
    req = urllib.request.Request(
        f"{args.api}/golden-sets",
        data=json.dumps(manifest).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        body = json.loads(resp.read())
    print(json.dumps(body, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
