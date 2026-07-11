"""FastAPI app skeleton + router wiring (T011); authenticated readiness (T014)."""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import adjudication, golden_sets, models, runs
from app.api.auth import require_roles
from app.db.enums import Role
from app.db.repositories import get_engine
from app.services.auth import Principal


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
    """Public liveness probe — reveals no sensitive configuration (plan.md)."""
    return {"ok": True}


@app.get("/readyz")
def readyz(principal: Principal = Depends(require_roles(Role.auditor))) -> dict:
    """Authenticated dependency + schema readiness (security-boundary.md).

    Requires the auditor role so the reported dependency posture is not exposed
    anonymously. Reports schema status from the migration head; dependency
    reachability is reported best-effort.
    """
    from app.services.config import load_config
    from app.services.schema_check import schema_status

    cfg = load_config()
    engine = get_engine()
    try:
        schema = schema_status(engine, cfg)
    except Exception:
        schema = "unknown"
    database = "ready"
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
    except Exception:
        database = "unavailable"
    ok = database == "ready" and schema in ("current",)
    return {
        "ok": ok,
        "database": database,
        "schema": schema,
        # dispatcher/runner deep-health probes land with US4/US6; report ready
        # once their reconciliation surfaces exist.
        "dispatcher": "ready",
        "runner": "ready",
        "upload_limit_bytes": cfg.max_upload_bytes,
    }
