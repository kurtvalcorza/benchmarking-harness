"""RQ worker entrypoint (T017/T057): consumes the `evaluations` queue.

    python -m worker.main

The worker executes `evaluate_intent` jobs (US4): each claims its durable
JobIntent before running and completes it in the run's transaction, so a
DUPLICATE transport delivery of a completed intent performs no new evaluation.

At boot it reconciles durable work that a prior crash/outage may have stranded:
- `dispatcher.run_once()` reclaims expired claim leases and (re)publishes any
  committed-but-unpublished intents — the transactional-outbox recovery path;
- `recover_orphaned_reevaluations()` re-enqueues re-evaluation claims whose job
  was lost before the JobIntent outbox existed / for the ReevaluationClaim path.

Production should ALSO run the dispatcher periodically (a cron/timer calling
`app.services.dispatcher.run_once`) so a broker outage during steady state is
drained without waiting for a restart.
"""

import os

from redis import Redis
from rq import Queue, Worker

from app.services.dispatcher import run_once
from app.services.orchestrator import recover_orphaned_reevaluations


def main() -> None:
    conn = Redis.from_url(os.environ.get("HARNESS_REDIS_URL", "redis://localhost:6379/0"))
    # durable-outbox recovery: reclaim expired leases + republish pending intents,
    # then rescue any pre-outbox re-evaluation claim whose job was lost
    run_once()
    recover_orphaned_reevaluations()
    worker = Worker([Queue("evaluations", connection=conn)], connection=conn)
    worker.work(with_scheduler=False)


if __name__ == "__main__":
    main()
