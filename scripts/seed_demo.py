#!/usr/bin/env python3
"""Seed the demo (T060): register the detection golden set, then submit one
healthy and one deliberately weak detector (owned toy weights from samples/).

    python scripts/seed_demo.py [--api http://localhost:8000]

Expected outcome (quickstart Scenarios A + B):
  healthy-detector → approved (three tiers pass, card generated)
  weak-detector    → pending_adjudication (pedestrian recall below floor)
"""

import argparse
import json
import mimetypes
import sys
import urllib.request
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MODELS = REPO / "samples" / "models"
sys.path.insert(0, str(REPO / "backend"))


def _auth_header(token: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token else {}


def dev_token() -> str:
    """Mint a local dev token with the roles the demo exercises (governance to
    register the golden set, submitter to upload). Requires dev auth; the API
    must share the default dev signing secret."""
    from app.services.auth import mint_dev_token
    from app.services.config import load_config

    cfg = load_config()
    if not cfg.dev_auth_enabled:
        raise SystemExit(
            "seed_demo needs dev auth (HARNESS_AUTH_MODE=dev, non-production); the API "
            "requires bearer tokens. Set up OIDC and pass --token for a real deployment."
        )
    return mint_dev_token("demo", ["governance", "submitter", "adjudicator", "auditor"], cfg=cfg)


def post_json(url: str, payload: dict, token: str | None = None) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **_auth_header(token)},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def post_multipart(
    url: str, fields: dict[str, list[str] | str], file_path: Path, token: str | None = None
) -> dict:
    boundary = uuid.uuid4().hex
    parts: list[bytes] = []
    for key, values in fields.items():
        for v in values if isinstance(values, list) else [values]:
            parts.append(
                (
                    f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{v}\r\n"
                ).encode()
            )
    ctype = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    parts.append(
        (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"weights\"; "
            f"filename=\"{file_path.name}\"\r\nContent-Type: {ctype}\r\n\r\n"
        ).encode()
        + file_path.read_bytes()
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            **_auth_header(token),
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--api", default="http://localhost:8000")
    p.add_argument(
        "--data-ref",
        default=str(REPO / "samples" / "golden" / "det-golden"),
        help="golden-set dir AS SEEN BY THE API/WORKER; with docker compose pass "
        "/srv/samples/golden/det-golden (samples are baked into the image)",
    )
    p.add_argument("--token", default=None, help="bearer token (defaults to a minted dev token)")
    args = p.parse_args()

    token = args.token or dev_token()

    golden = post_json(
        f"{args.api}/golden-sets",
        {
            "name": "det-golden",
            "model_class": "detection",
            "version": "v1",
            "checksum": "auto",
            "conditions": ["rain", "low_light", "fog"],
            "safety_critical": ["pedestrian"],
            "recall_floors": {"pedestrian": 0.6},
            "license": "owned",
            "is_public": False,
            "domain": "local-context-demo",
            "data_ref": args.data_ref,
        },
        token=token,
    )
    print(f"golden set registered: {golden['id']} checksum {golden['checksum'][:12]}…")

    for name, weights in (
        ("healthy-detector", MODELS / "healthy_detector.stub.json"),
        ("weak-detector", MODELS / "weak_detector.stub.json"),
    ):
        mv = post_multipart(
            f"{args.api}/models",
            {
                "name": name,
                "model_class": "detection",
                "framework": "stub",
                "version": "v1",
                "declared_sources": ["synthetic training set v1 (owned)"],
            },
            weights,
            token=token,
        )
        print(f"submitted {name}: version {mv['id']} status {mv['status']}")
    print("open the UI: healthy → approved; weak → adjudication queue")
    return 0


if __name__ == "__main__":
    sys.exit(main())
