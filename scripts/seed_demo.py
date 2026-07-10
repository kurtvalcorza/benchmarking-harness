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


def post_json(url: str, payload: dict) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def post_multipart(url: str, fields: dict[str, list[str] | str], file_path: Path) -> dict:
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
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--api", default="http://localhost:8000")
    args = p.parse_args()

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
            "data_ref": str(REPO / "samples" / "golden" / "det-golden"),
        },
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
        )
        print(f"submitted {name}: version {mv['id']} status {mv['status']}")
    print("open the UI: healthy → approved; weak → adjudication queue")
    return 0


if __name__ == "__main__":
    sys.exit(main())
