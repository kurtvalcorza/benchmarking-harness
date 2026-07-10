"""No-egress sandbox runner (T014, T065, Constitution IV).

Executes engine.sandbox.job in an isolated environment:

- **docker** mode (default when a daemon is reachable): ephemeral container,
  `network_disabled` (== `--network none`), READ-ONLY mounts for code, weights
  and dataset, a writable tmpfs-backed out dir only, CPU/memory caps, and a
  hard wall-clock timeout. Container is force-removed afterwards.
- **subprocess** mode (POC fallback / CI without a daemon): a separate python
  process with the HARNESS_SANDBOX_GUARD socket guard; the job's runtime
  no-egress assertion still runs.

Every result carries `sandbox_mode` so the evidence trail records how the run
was isolated.
"""

import json
import os
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]

DOCKER_IMAGE = os.environ.get("HARNESS_SANDBOX_IMAGE", "benchmarking-harness-sandbox:latest")
CPU_CAP = float(os.environ.get("HARNESS_SANDBOX_CPUS", "2"))
MEM_CAP = os.environ.get("HARNESS_SANDBOX_MEM", "4g")
TIMEOUT_S = int(os.environ.get("HARNESS_SANDBOX_TIMEOUT", "1800"))


class SandboxError(RuntimeError):
    """Infrastructure failure inside/around the sandbox (→ infra_ok=false)."""


@dataclass
class JobResult:
    ok: bool
    sandbox_mode: str
    raw: dict

    @property
    def predictions(self) -> list[dict]:
        return self.raw.get("predictions", [])

    @property
    def descriptor(self) -> dict:
        return self.raw.get("descriptor", {})

    @property
    def timing(self) -> dict:
        return self.raw.get("timing", {})

    @property
    def adapter_error(self) -> str | None:
        return self.raw.get("error") if self.raw.get("error_kind") == "adapter" else None


def sandbox_mode() -> str:
    mode = os.environ.get("HARNESS_SANDBOX_MODE", "auto")
    if mode in ("docker", "subprocess"):
        return mode
    return "docker" if _docker_available() else "subprocess"


def _docker_available() -> bool:
    try:
        import docker

        docker.from_env().ping()
        return True
    except Exception:
        return False


def run_inference(
    *, framework: str, artifact: str, model_class: str, dataset_root: str
) -> JobResult:
    mode = sandbox_mode()
    with tempfile.TemporaryDirectory(prefix="harness-sandbox-") as tmp:
        out_dir = Path(tmp)
        if mode == "docker":
            raw = _run_docker(framework, artifact, model_class, dataset_root, out_dir)
        else:
            raw = _run_subprocess(framework, artifact, model_class, dataset_root, out_dir)
    return JobResult(ok=bool(raw.get("ok")), sandbox_mode=mode, raw=raw)


def docker_container_config(
    framework: str, artifact: str, model_class: str, dataset_root: str, out_dir: Path
) -> dict:
    """The exact hardening config handed to docker (unit-testable without a
    daemon; reviewed by T065 / asserted by tests/contract/test_sandbox_no_egress.py).

    CI has no docker service, so this config is asserted as data but not
    exercised against a live daemon there — validate on a docker host before
    relying on the docker path in production (the runtime no-egress assertion
    in engine.sandbox.job is the independent backstop either way)."""
    return {
        "image": DOCKER_IMAGE,
        "command": ["python", "-m", "engine.sandbox.job", "--spec", "/mnt/out/spec.json"],
        "network_disabled": True,  # --network none
        "network_mode": "none",
        "read_only": True,  # read-only root fs
        "volumes": {
            str(BACKEND_ROOT): {"bind": "/srv/backend", "mode": "ro"},
            str(Path(artifact).resolve()): {"bind": "/mnt/artifact", "mode": "ro"},
            str(Path(dataset_root).resolve()): {"bind": "/mnt/dataset", "mode": "ro"},
            str(out_dir): {"bind": "/mnt/out", "mode": "rw"},
        },
        "tmpfs": {"/tmp": "rw,size=256m"},
        "working_dir": "/srv/backend",
        "environment": {"PYTHONPATH": "/srv/backend"},
        "nano_cpus": int(CPU_CAP * 1e9),
        "mem_limit": MEM_CAP,
        "pids_limit": 256,
        "detach": True,
        "auto_remove": False,  # we remove after log/exit collection
        "name": f"harness-run-{uuid.uuid4().hex[:12]}",
    }


def _run_docker(
    framework: str, artifact: str, model_class: str, dataset_root: str, out_dir: Path
) -> dict:
    try:
        import docker
    except ImportError as e:
        raise SandboxError("docker SDK not installed (pip install '.[ml]')") from e

    spec = {
        "framework": framework,
        "artifact": "/mnt/artifact",
        "model_class": model_class,
        "dataset": "/mnt/dataset",
        "out": "/mnt/out/result.json",
    }
    (out_dir / "spec.json").write_text(json.dumps(spec))
    cfg = docker_container_config(framework, artifact, model_class, dataset_root, out_dir)
    client = docker.from_env()
    container = client.containers.run(**cfg)
    try:
        status = container.wait(timeout=TIMEOUT_S)
        if status.get("StatusCode", 1) not in (0, 3):
            logs = container.logs().decode(errors="replace")[-2000:]
            raise SandboxError(f"sandbox job exited {status}: {logs}")
    finally:
        try:
            container.remove(force=True)  # ephemeral — nothing survives the run
        except Exception:
            pass
    return _read_result(out_dir)


def _run_subprocess(
    framework: str, artifact: str, model_class: str, dataset_root: str, out_dir: Path
) -> dict:
    spec = {
        "framework": framework,
        "artifact": str(Path(artifact).resolve()),
        "model_class": model_class,
        "dataset": str(Path(dataset_root).resolve()),
        "out": str(out_dir / "result.json"),
    }
    spec_path = out_dir / "spec.json"
    spec_path.write_text(json.dumps(spec))
    env = {
        **os.environ,
        "HARNESS_SANDBOX_GUARD": "1",
        "PYTHONPATH": str(BACKEND_ROOT),
    }
    proc = subprocess.run(
        [sys.executable, "-m", "engine.sandbox.job", "--spec", str(spec_path)],
        cwd=str(BACKEND_ROOT),
        env=env,
        capture_output=True,
        timeout=TIMEOUT_S,
    )
    if proc.returncode not in (0, 3):
        raise SandboxError(
            f"sandbox job exited {proc.returncode}: {proc.stderr.decode(errors='replace')[-2000:]}"
        )
    return _read_result(out_dir)


def _read_result(out_dir: Path) -> dict:
    result_path = out_dir / "result.json"
    if not result_path.exists():
        raise SandboxError("sandbox job produced no result.json")
    return json.loads(result_path.read_text())
