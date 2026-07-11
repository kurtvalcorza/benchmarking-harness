"""Dedicated runner service (T073/T074, US6).

This is the ONLY component that holds the container runtime socket. The API and
general worker delegate model execution here over HTTP (runner_client.py) so a
compromised evaluation path cannot reach the host Docker daemon from the API/UI
tier. Run it in the compose ``production`` profile with the socket mounted:

    uvicorn runner.main:app --host 0.0.0.0 --port 9000

Auth: a shared bearer secret (HARNESS_RUNNER_TOKEN) gates /run so only the
worker can drive it. The runner enforces the same path allowlist (T072) and
no-egress sandbox (Constitution IV) as the in-process path — it simply owns the
socket the rest of the stack must not.
"""

import os

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from engine.sandbox.runner import SandboxError, run_inference

app = FastAPI(title="Benchmarking Harness Runner", version="0.1.0")


class RunRequest(BaseModel):
    framework: str
    artifact: str
    model_class: str
    dataset_root: str


def _authorize(authorization: str | None) -> None:
    expected = os.environ.get("HARNESS_RUNNER_TOKEN", "")
    if not expected:
        # fail closed: a runner exposed without a shared secret would let anything
        # on the network drive host-socket execution
        raise HTTPException(503, "runner not configured (HARNESS_RUNNER_TOKEN unset)")
    presented = (authorization or "").removeprefix("Bearer ").strip()
    if presented != expected:
        raise HTTPException(401, "invalid runner token")


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.post("/run")
def run(body: RunRequest, authorization: str | None = Header(default=None)) -> dict:
    _authorize(authorization)
    try:
        # HARNESS_RUNNER_URL is intentionally UNSET in the runner's own env, so
        # this executes the sandbox LOCALLY (owning the socket) — never recurses.
        result = run_inference(
            framework=body.framework,
            artifact=body.artifact,
            model_class=body.model_class,
            dataset_root=body.dataset_root,
        )
    except SandboxError as e:
        raise HTTPException(502, f"sandbox execution failed: {e}") from e
    return {"ok": result.ok, "sandbox_mode": result.sandbox_mode, "raw": result.raw}
