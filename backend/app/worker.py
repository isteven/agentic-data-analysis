import asyncio
import json
import logging
import uuid

from saq import Queue

from app.agents.state import TraceEvent, new_state
from app.agents.trace import (
    TRACE_STREAM_TTL_SECONDS,
    reset_trace_sink,
    set_trace_sink,
    trace_stream_key,
)
from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.services.query_service import mark_run_failed, persist_run, run_graph

logger = logging.getLogger(__name__)

settings = get_settings()

queue = Queue.from_url(settings.redis_url, name="apda")


async def run_query_task(
    ctx: dict, *, run_id: str, query_text: str, provider: str | None = None
) -> dict:
    """Runs the agent graph and appends each trace event to the run's Redis Stream as
    it is emitted (read by GET /api/agent-trace/{run_id}), then persists the run.

    Whatever fails, the run ends: it is saved with a final status (or marked failed),
    and the stream always gets "done" - otherwise a poller or SSE client waits for a
    run that will never finish.
    """
    redis = ctx["redis"]
    stream = trace_stream_key(run_id)
    run_uuid = uuid.UUID(run_id)

    # emit_trace is synchronous and called deep inside nodes; it only enqueues, and this
    # task does the Redis writes, in emission order.
    pending: asyncio.Queue[TraceEvent | None] = asyncio.Queue()

    async def pump() -> None:
        while (event := await pending.get()) is not None:
            try:
                await redis.xadd(stream, {"event": json.dumps(event)})
            except Exception:  # a lost live event must not fail the run
                logger.exception("[DEBUG] trace publish failed run_id=%s", run_id)

    pump_task = asyncio.create_task(pump())
    token = set_trace_sink(pending.put_nowait)

    state = new_state(query=query_text, run_id=run_id, provider=provider)
    try:
        final_state = await run_graph(AsyncSessionLocal, state)
    except asyncio.CancelledError:
        # SAQ cancels the task itself on a job timeout - a plain `except Exception`
        # never sees this (CancelledError is a BaseException since 3.8). Without this
        # branch the run is orphaned at status "running" forever.
        logger.warning("[DEBUG] run_query_task cancelled (job timeout) run_id=%s", run_id)
        state["errors"].append({"node_name": "graph", "message": "Timed out before finishing."})
        state["status"] = "failed"
        final_state = state
    finally:
        reset_trace_sink(token)
        pending.put_nowait(None)
        await pump_task

    status = await _save(run_uuid, query_text, final_state)
    await _close_stream(redis, stream, status, run_id)
    return {"run_id": run_id, "status": status}


async def _save(run_id: uuid.UUID, query_text: str, final_state: dict) -> str:
    """Persist the run in a fresh session; if that fails, at least end it as failed."""
    try:
        async with AsyncSessionLocal() as session:
            run, _ = await persist_run(session, run_id, query_text, final_state)
            return run.status
    except Exception:
        logger.exception("[DEBUG] persist_run failed run_id=%s; marking the run failed", run_id)
    try:
        async with AsyncSessionLocal() as session:
            await mark_run_failed(session, run_id, "The run finished but couldn't be saved.")
    except Exception:
        logger.exception("[DEBUG] mark_run_failed failed run_id=%s", run_id)
    return "failed"


async def _close_stream(redis, stream: str, status: str, run_id: str) -> None:
    """After the save, so a subscriber that sees "done" can fetch the finished run."""
    try:
        await redis.xadd(stream, {"done": status})
        await redis.expire(stream, TRACE_STREAM_TTL_SECONDS)
    except Exception:  # subscribers fall back to polling the saved run
        logger.exception("[DEBUG] closing trace stream failed run_id=%s", run_id)


async def startup(ctx: dict) -> None:
    ctx["redis"] = queue.redis


settings_dict = {
    "queue": queue,
    "functions": [run_query_task],
    "startup": startup,
    "concurrency": 4,
    # Default 1s isn't enough for run_query_task's CancelledError handler to persist_run
    # (a DB write) after a job-timeout cancellation; give it real room to finish cleanly
    # rather than being force-killed mid-write and leaving the run stuck at "running".
    "cancellation_hard_deadline_s": 15,
}
