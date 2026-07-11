"""Runner-service client (T073, US6).

The API and general worker MUST NOT hold an unrestricted Docker socket — a
compromised evaluation path could otherwise escape to the host. When
``HARNESS_RUNNER_URL`` is configured, model execution is delegated over HTTP to
a dedicated runner service that is the ONLY component with the runtime socket
(docker-compose ``production`` profile). Without it, execution stays in-process
(the offline/dev default).

Trust boundary: the call carries a shared bearer secret (``HARNESS_RUNNER_TOKEN``)
so only the worker can drive the runner. Artifact/dataset paths are passed by
reference and MUST resolve identically on both sides (shared read-only volumes);
the runner re-validates them against its own allowlist (T072).
"""

import os

from engine.sandbox.runner import JobResult, SandboxError


def runner_url() -> str | None:
    return os.environ.get("HARNESS_RUNNER_URL") or None


def run_remote(
    *, framework: str, artifact: str, model_class: str, dataset_root: str
) -> JobResult:
    """Execute inference on the dedicated runner service. Raises SandboxError on
    transport/HTTP failure so the orchestrator records an infra failure (never a
    model `fail`)."""
    import httpx

    url = runner_url()
    if not url:
        raise SandboxError("run_remote called without HARNESS_RUNNER_URL configured")
    token = os.environ.get("HARNESS_RUNNER_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    # One run_remote call executes ONE tier's sandbox inference (Tier 2 calls it
    # per condition), bounded by the sandbox wall-clock ceiling
    # (HARNESS_SANDBOX_TIMEOUT, default 1800s) — NOT the whole 3-tier run. Give
    # the HTTP call that ceiling plus headroom for container start/teardown, and
    # keep it comfortably BELOW the RQ job deadline (job_timeout=7200s) so a hung
    # runner raises a clean per-call SandboxError (infra failure) before RQ kills
    # the worker and leaves the intent to stale-lease reconciliation.
    sandbox_ceiling = int(os.environ.get("HARNESS_SANDBOX_TIMEOUT", "1800"))
    default_timeout = min(sandbox_ceiling + 300, 7200 - 120)
    timeout = float(os.environ.get("HARNESS_RUNNER_HTTP_TIMEOUT", str(default_timeout)))
    try:
        resp = httpx.post(
            url.rstrip("/") + "/run",
            json={
                "framework": framework,
                "artifact": artifact,
                "model_class": model_class,
                "dataset_root": dataset_root,
            },
            headers=headers,
            timeout=timeout,
        )
    except httpx.HTTPError as e:
        raise SandboxError(f"runner service unreachable at {url}: {e}") from e
    if resp.status_code != 200:
        raise SandboxError(
            f"runner service returned {resp.status_code}: {resp.text[:500]}"
        )
    body = resp.json()
    return JobResult(
        ok=bool(body.get("ok")),
        sandbox_mode=body.get("sandbox_mode", "docker"),
        raw=body.get("raw", {}),
    )
