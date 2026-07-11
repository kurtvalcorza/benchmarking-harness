"""FastAPI app skeleton + router wiring (T011)."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import adjudication, golden_sets, models, runs
from app.db.repositories import get_engine


@asynccontextmanager
async def _lifespan(app: FastAPI):
    get_engine()
    # inline mode has no worker to reclaim lost re-evaluation jobs on boot, so
    # the app owns that reconciliation; in rq mode the worker does it instead
    # (see worker/main.py) to avoid two processes racing the same orphan
    from app.services.orchestrator import eval_mode, recover_orphaned_reevaluations

    if eval_mode() == "inline":
        recover_orphaned_reevaluations()
    yield


app = FastAPI(
    lifespan=_lifespan,
    title="Model Benchmarking Harness API (POC)",
    version="0.1.0",
    description=(
        "Gates CV models via a three-tier evaluation with a mandatory "
        "single-reviewer adjudication step. There is NO endpoint that "
        "force-approves a flagged model (Constitution I)."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(models.router)
app.include_router(runs.router)
app.include_router(golden_sets.router)
app.include_router(adjudication.router)


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}
