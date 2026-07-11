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
REPO_ROOT = BACKEND_ROOT.parent

DOCKER_IMAGE = os.environ.get("HARNESS_SANDBOX_IMAGE", "benchmarking-harness-sandbox:latest")
CPU_CAP = float(os.environ.get("HARNESS_SANDBOX_CPUS", "2"))
MEM_CAP = os.environ.get("HARNESS_SANDBOX_MEM", "4g")
TIMEOUT_S = int(os.environ.get("HARNESS_SANDBOX_TIMEOUT", "1800"))
# non-root identity the model process runs as inside the container (matches the
# `nonroot` user baked into docker/sandbox.Dockerfile)
SANDBOX_UID_GID = os.environ.get("HARNESS_SANDBOX_USER", "65532:65532")
SECCOMP_PROFILE = Path(
    os.environ.get("HARNESS_SANDBOX_SECCOMP", str(REPO_ROOT / "docker" / "sandbox-seccomp.json"))
)


def _seccomp_opt() -> str | None:
    """Return the `seccomp=<json>` security_opt from the pinned profile, or None
    if the profile file is absent (docker then applies its default profile)."""
    try:
        return "seccomp=" + SECCOMP_PROFILE.read_text()
    except OSError:
        return None


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


# Frameworks whose adapters execute ONLY code from this repository. Untrusted
# weights (pytorch pickles, onnx graphs) may spawn child processes or use
# native networking that the subprocess mode's Python-level socket guard
# cannot see — those frameworks REQUIRE the docker sandbox (fail closed).
_SUBPROCESS_SAFE_FRAMEWORKS = {"stub"}


def _allowed_roots() -> tuple[list[Path], list[Path]]:
    """(input_roots, output_roots) the sandbox may read/write. Attacker-
    influenceable artifact/dataset paths must resolve beneath an input root;
    the output dir beneath an output root. Enforced here as defence in depth
    on top of Golden Set registration containment (T020a)."""
    from app.services.config import load_config

    cfg = load_config()
    work = os.environ.get("HARNESS_SANDBOX_WORKDIR")
    temp_roots = [Path(tempfile.gettempdir())]
    if work:
        temp_roots.append(Path(work))
    input_roots = [
        cfg.artifacts_root,
        *cfg.data_roots,
        cfg.results_root,
        cfg.runner_work_root,
        *temp_roots,  # Tier 2 writes perturbed dataset copies here
    ]
    output_roots = [cfg.results_root, cfg.runner_work_root, *temp_roots]
    return input_roots, output_roots


def _assert_paths_allowed(artifact: str, dataset_root: str, out_dir: Path) -> None:
    from app.services.config import resolves_beneath

    input_roots, output_roots = _allowed_roots()
    for label, raw in (("artifact", artifact), ("dataset", dataset_root)):
        if not resolves_beneath(Path(raw), tuple(input_roots)):
            raise SandboxError(
                f"sandbox refuses {label} path outside the allowlisted roots "
                f"(path containment, T072): {raw}"
            )
    if not resolves_beneath(out_dir, tuple(output_roots)):
        raise SandboxError(
            f"sandbox refuses output path outside the allowlisted roots (T072): {out_dir}"
        )


def run_inference(
    *, framework: str, artifact: str, model_class: str, dataset_root: str
) -> JobResult:
    # T073: when a dedicated runner service is configured, the API/worker holds
    # NO container socket — delegate execution over HTTP. The runner service runs
    # with HARNESS_RUNNER_URL unset, so it executes locally (no recursion).
    if os.environ.get("HARNESS_RUNNER_URL"):
        from app.services.runner_client import run_remote

        return run_remote(
            framework=framework,
            artifact=artifact,
            model_class=model_class,
            dataset_root=dataset_root,
        )
    mode = sandbox_mode()
    if (
        mode == "subprocess"
        and framework not in _SUBPROCESS_SAFE_FRAMEWORKS
        and os.environ.get("HARNESS_ALLOW_UNSANDBOXED_FRAMEWORKS") != "1"
    ):
        raise SandboxError(
            f"the subprocess sandbox only guards Python-level sockets and cannot contain "
            f"untrusted '{framework}' weights (child processes / native networking bypass "
            f"it) — run a docker daemon for real models, or set "
            f"HARNESS_ALLOW_UNSANDBOXED_FRAMEWORKS=1 for trusted local development only"
        )
    # HARNESS_SANDBOX_WORKDIR: where per-run out dirs are created. Needed when
    # the worker runs in a container and the docker daemon resolves bind mounts
    # on the host — point it at a directory covered by HARNESS_HOSTPATH_MAP.
    workdir = os.environ.get("HARNESS_SANDBOX_WORKDIR")
    if workdir:
        Path(workdir).mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="harness-sandbox-", dir=workdir or None) as tmp:
        out_dir = Path(tmp)
        # T072: refuse to mount artifact/dataset/output paths that escape the
        # configured roots (a malicious data_ref/artifact cannot reach host files)
        _assert_paths_allowed(artifact, dataset_root, out_dir)
        if mode == "docker":
            raw = _run_docker(framework, artifact, model_class, dataset_root, out_dir)
        else:
            raw = _run_subprocess(framework, artifact, model_class, dataset_root, out_dir)
    return JobResult(ok=bool(raw.get("ok")), sandbox_mode=mode, raw=raw)


def _hostpath_pairs() -> list[tuple[str, str]]:
    """HARNESS_HOSTPATH_MAP='/container/path=/host/path;...' — longest prefix wins."""
    pairs = []
    for entry in os.environ.get("HARNESS_HOSTPATH_MAP", "").split(";"):
        if "=" in entry:
            cont, host = entry.split("=", 1)
            if cont.strip() and host.strip():
                pairs.append((cont.strip().rstrip("/"), host.strip().rstrip("/")))
    return sorted(pairs, key=lambda p: -len(p[0]))


def _host_path(path: str) -> str:
    """Translate a container-local path to the daemon-visible host path.

    When the worker itself runs inside a container and talks to the host's
    docker daemon over /var/run/docker.sock, bind-mount SOURCES are resolved
    by the daemon on the HOST — container paths like /srv/state/... don't
    exist there. HARNESS_HOSTPATH_MAP declares the translation (see
    docker-compose.yml). Without the env var this is the identity function.
    """
    s = str(Path(path).resolve())
    for cont, host in _hostpath_pairs():
        if s == cont or s.startswith(cont + "/"):
            return host + s[len(cont):]
    return s


def docker_container_config(
    framework: str, artifact: str, model_class: str, dataset_root: str, out_dir: Path
) -> dict:
    """The exact hardening config handed to docker (unit-testable without a
    daemon; reviewed by T065 / asserted by tests/contract/test_sandbox_no_egress.py).

    CI has no docker service, so this config is asserted as data but not
    exercised against a live daemon there — validate on a docker host before
    relying on the docker path in production (the runtime no-egress assertion
    in engine.sandbox.job is the independent backstop either way)."""
    # keep the artifact's real filename (and thus extension) inside the
    # container: adapters dispatch on suffix, so a bare /mnt/artifact would
    # make every real .pt/.onnx submission unloadable in docker mode (F9)
    artifact_target = f"/mnt/artifact/{Path(artifact).name}"
    # T071: no-new-privileges + the pinned seccomp profile (security_opt);
    # cap_drop ALL, a non-root user, a read-only root fs, no network, and a
    # bounded noexec/nosuid/nodev tmpfs are defence-in-depth around untrusted
    # model code (security-boundary.md).
    security_opt = ["no-new-privileges:true"]
    seccomp = _seccomp_opt()
    if seccomp:
        security_opt.append(seccomp)
    return {
        "image": DOCKER_IMAGE,
        "command": ["python", "-m", "engine.sandbox.job", "--spec", "/mnt/out/spec.json"],
        "network_disabled": True,  # --network none
        "network_mode": "none",
        "read_only": True,  # read-only root fs
        "user": SANDBOX_UID_GID,  # non-root
        "cap_drop": ["ALL"],
        "security_opt": security_opt,
        "volumes": {
            _host_path(str(BACKEND_ROOT)): {"bind": "/srv/backend", "mode": "ro"},
            _host_path(artifact): {"bind": artifact_target, "mode": "ro"},
            _host_path(dataset_root): {"bind": "/mnt/dataset", "mode": "ro"},
            _host_path(str(out_dir)): {"bind": "/mnt/out", "mode": "rw"},
        },
        "tmpfs": {"/tmp": "rw,nosuid,nodev,noexec,size=256m"},
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
        "artifact": f"/mnt/artifact/{Path(artifact).name}",
        "model_class": model_class,
        "dataset": "/mnt/dataset",
        "out": "/mnt/out/result.json",
    }
    (out_dir / "spec.json").write_text(json.dumps(spec))
    # the container runs as the non-root UID 65532, but this host-owned tmp out
    # dir is 0700/worker-owned — without this the sandbox cannot traverse the
    # bind mount to read spec.json or write result.json (docker evals would all
    # infra-fail). The dir is ephemeral, per-run, and removed afterwards.
    try:
        os.chmod(out_dir, 0o777)
        os.chmod(out_dir / "spec.json", 0o644)
    except OSError:
        pass
    cfg = docker_container_config(framework, artifact, model_class, dataset_root, out_dir)
    try:
        client = docker.from_env()
        container = client.containers.run(**cfg)
    except Exception as e:  # daemon unreachable / image missing / bad config
        raise SandboxError(f"docker sandbox failed to start: {e}") from e
    try:
        try:
            status = container.wait(timeout=TIMEOUT_S)
        except Exception as e:  # timeout or daemon error mid-run → infra, not a model fail
            raise SandboxError(f"sandbox job timed out or died: {e}") from e
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
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "engine.sandbox.job", "--spec", str(spec_path)],
            cwd=str(BACKEND_ROOT),
            env=env,
            capture_output=True,
            timeout=TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as e:  # infra failure, never a model `fail`
        raise SandboxError(f"sandbox job timed out after {TIMEOUT_S}s") from e
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
