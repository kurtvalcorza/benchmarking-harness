"""RQ worker entrypoint (T017): consumes the `evaluations` queue.

    python -m worker.main
"""

import os

from redis import Redis
from rq import Queue, Worker


def main() -> None:
    conn = Redis.from_url(os.environ.get("HARNESS_REDIS_URL", "redis://localhost:6379/0"))
    worker = Worker([Queue("evaluations", connection=conn)], connection=conn)
    worker.work(with_scheduler=False)


if __name__ == "__main__":
    main()
