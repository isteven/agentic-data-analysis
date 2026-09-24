"""CLI inspection for the SAQ job queue - `uv run python -m scripts.queue_status`.

Skips standing up SAQ's optional web UI (unnecessary extra surface for this
project's scope); wraps the same Queue.info()/iter_jobs() calls the web UI
itself would use.
"""

import asyncio

from app.worker import queue


async def main() -> None:
    info = await queue.info(jobs=True)
    print(f"Queue: {queue.name}")
    print(
        f"Counts: {info['queued']} queued, {info['active']} active, {info['scheduled']} scheduled"
    )
    for job in info.get("jobs", []):
        status = job.get("status", "?")
        function = job.get("function", "?")
        kwargs = job.get("kwargs", {})
        key = job.get("key", "?")
        print(f"  [{status:>9}] {function}({kwargs}) key={key}")


if __name__ == "__main__":
    asyncio.run(main())
