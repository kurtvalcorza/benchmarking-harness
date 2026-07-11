# Runbook — Durable-Work Recovery

Feature 002 makes evaluation dispatch a **durable transactional outbox**, so most
faults self-heal. This runbook covers the operator-visible failure modes: queue
outage, stuck job intents, orphaned evidence, and a runner outage.

## Health signal

`/readyz` (auditor bearer token) reports the reconciliation summary:

```json
{
  "ok": true,
  "schema": "current",
  "dispatcher": {
    "status": "ready|degraded",
    "intents": {"by_state": {...}, "stuck": 0, "failed": 0},
    "orphaned_evidence": 0
  }
}
```

`dispatcher.status == "degraded"` means there are stuck intents (expired leases),
failed intents, or orphaned evidence — investigate below. `ok` stays true (the
instance can still serve) while a background sweep clears the backlog.

## 1. Queue (Redis) outage

**Symptom**: submissions still return `201` (the durable intent committed), but
evaluations do not start; `intents.by_state.pending` grows.

**Why it is safe**: the submission's `JobIntent` commits in the same transaction
as the ModelVersion + receipt, so nothing is lost (FR-016/018). The API does not
`503`.

**Recovery**: once Redis is back, run a dispatcher sweep (the worker also does
this at boot):

```python
# from the app/worker environment
from app.services.dispatcher import run_once
run_once()          # reclaims expired leases + republishes pending intents
```

Production should run `dispatcher.run_once()` on a timer (cron/systemd) so a
steady-state outage drains without a restart.

## 2. Stuck intents (expired leases / dead worker)

**Symptom**: `intents.stuck > 0`; a version sits in `evaluating` after a worker
crash/OOM.

**Why it is safe**: a claim holds a lease (`HARNESS_JOB_LEASE_SECONDS`, default
7200s — covers a full 3-tier run). If the worker dies, the lease expires.

**Recovery**: `dispatcher.reclaim_expired_leases()` (part of `run_once()`) returns
the intent to `pending` AND releases the stale `evaluating` mutex on its version
(resets it to `pending`), so the re-dispatch re-runs it cleanly — no poison loop.
Duplicate delivery of an already-completed intent is a no-op (FR-017).

```python
from app.services.dispatcher import reclaim_expired_leases, dispatch_pending
reclaim_expired_leases()   # release dead workers' claims + stale evaluating
dispatch_pending()         # re-publish
```

Retryable failures back off exponentially and park in `failed` after
`HARNESS_JOB_MAX_ATTEMPTS` (default 5); a `failed` intent needs an operator retry
(re-enqueue) after the root cause is fixed.

## 3. Orphaned evidence

**Symptom**: `orphaned_evidence > 0`.

**Cause**: a crash between `EvidenceStage.stage` and `publish`/`discard` left a
staging directory with no committed run. These are harmless bytes (no DB row).

**Recovery**: `reconciliation.orphaned_evidence(results_dir())` lists the run ids;
after confirming no matching TierResult exists, remove the staging directories:

```bash
# results_root/staging/<run_id>/  — safe to delete once reported orphaned
rm -rf "$HARNESS_RESULTS_DIR/staging/<run_id>"
```

Content-addressed grounding artifacts under `results_root/evidence/<digest>.json`
are idempotent and shareable across runs — leave them.

## 4. Runner-service outage (production socket boundary)

**Symptom**: evaluations infra-fail with "runner service unreachable"; the version
returns to `pending` (infra failure ≠ model fail).

**Why it is safe**: the API/worker hold no container socket; only the runner does
(FR-025). An unreachable runner is an infra failure that the durable intent will
retry.

**Recovery**:
1. Confirm the runner is up: `curl http://runner:9000/healthz` → `{"ok": true}`.
2. Confirm the worker's `HARNESS_RUNNER_URL` + `HARNESS_RUNNER_TOKEN` match the
   runner's `HARNESS_RUNNER_TOKEN` (the runner fails closed / returns 401/503 on
   mismatch or unset secret).
3. Restart the runner if needed; then `dispatcher.run_once()` re-dispatches the
   pending/reclaimed intents.

## Invariants preserved throughout

- No completed/approved state without its current Model Card (atomic completion).
- No duplicate logical evaluation run from at-least-once delivery.
- No user re-submission required for a committed submission/registration.
- Append-only history and audit trail remain intact (Constitution IV).
