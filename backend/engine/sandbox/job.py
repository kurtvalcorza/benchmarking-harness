"""In-sandbox inference job (D1). ALL model inference runs through this
entrypoint — never in the API/worker process (data-model.md validation rule).

    python -m engine.sandbox.job --spec /path/to/spec.json

Spec: {framework, artifact, model_class, dataset, out}

The job begins with a RUNTIME NO-NETWORK ASSERTION (Constitution IV, D1): it
actively attempts an outbound connection and ABORTS if one succeeds — a
reachable network means the sandbox is not isolated. Under the docker runner
this is guaranteed by `--network none`; under the subprocess fallback a socket
guard (HARNESS_SANDBOX_GUARD=1) blocks outbound connects before the assertion
runs.
"""

import argparse
import json
import socket
import sys
import time
from pathlib import Path


def _install_socket_guard() -> None:
    """Subprocess-fallback egress guard: refuse any non-loopback connect."""
    real_connect = socket.socket.connect

    def guarded(self, address):  # noqa: ANN001
        host = address[0] if isinstance(address, tuple) else str(address)
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise OSError(f"sandbox egress blocked: connect to {host!r} denied")
        return real_connect(self, address)

    socket.socket.connect = guarded  # type: ignore[method-assign]


def assert_no_egress(timeout: float = 2.0) -> None:
    """Abort the run if the network is reachable from inside the sandbox."""
    probes = [("1.1.1.1", 443), ("8.8.8.8", 53)]
    for host, port in probes:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                pass
        except OSError:
            continue  # unreachable — exactly what we want
        raise SystemExit(
            f"SANDBOX VIOLATION: outbound connection to {host}:{port} succeeded; "
            "refusing to run inference (Constitution IV / D1)"
        )


def run(spec: dict) -> dict:
    from app.db.enums import ModelClass
    from engine.adapters.base import AdapterError, get_adapter
    from engine.datasets import Dataset

    model_class = ModelClass(spec["model_class"])
    adapter = get_adapter(spec["framework"])
    dataset = Dataset(root=Path(spec["dataset"]))
    images = dataset.images()

    t0 = time.perf_counter()
    try:
        model = adapter.load(spec["artifact"], model_class)
    except AdapterError as e:
        return {"ok": False, "error_kind": "adapter", "error": str(e)}
    t_load = time.perf_counter() - t0

    t1 = time.perf_counter()
    try:
        preds = adapter.predict(model, images)
    except AdapterError as e:
        return {"ok": False, "error_kind": "adapter", "error": str(e)}
    t_pred = time.perf_counter() - t1

    desc = adapter.describe(model)
    return {
        "ok": True,
        "egress_asserted": True,
        "predictions": [p.to_dict() for p in preds],
        "descriptor": desc.to_dict(),
        "timing": {
            "load_s": round(t_load, 4),
            "predict_s": round(t_pred, 4),
            "num_images": len(images),
            "latency_ms_per_image": round(1000 * t_pred / len(images), 2) if images else None,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", required=True)
    args = parser.parse_args()
    spec = json.loads(Path(args.spec).read_text())

    import os

    if os.environ.get("HARNESS_SANDBOX_GUARD") == "1":
        _install_socket_guard()
    assert_no_egress()

    result = run(spec)
    Path(spec["out"]).write_text(json.dumps(result))
    return 0 if result.get("ok") else 3


if __name__ == "__main__":
    sys.exit(main())
