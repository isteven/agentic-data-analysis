import asyncio
import json
import logging
import uuid

from saq import Queue

from app.agents.graph import build_graph
from app.agents.state import TraceEvent, new_state
from app.agents.trace import (
    TRACE_STREAM_TTL_SECONDS,
    reset_trace_sink,
    set_trace_sink,
    trace_stream_key,
)
from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.services.query_service import persist_run

logger = logging.getLogger(__name__)

settings = get_settings()

queue = Queue.from_url(settings.redis_url, name="apda")


async def run_query_task(
    ctx: dict, *, run_id: str, query_text: str, provider: str | None = None
) -> dict:
    """Runs the agent graph and appends each trace event to the run's Redis Stream as
    it is emitted (read by GET /api/agent-trace/{run_id}), then persists the run."""
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

    async with AsyncSessionLocal() as session:
        graph = build_graph(session)
        state = new_state(query=query_text, run_id=run_id, provider=provider)
        try:
            final_state = await graph.ainvoke(state)
            final_state["status"] = "completed" if not final_state.get("errors") else "partial"
        except Exception as exc:  # unrecoverable graph failure: degrade gracefully
            logger.exception("[DEBUG] graph failed run_id=%s", run_id)
            final_state = state
            final_state["errors"].append({"node_name": "graph", "message": str(exc)})
            final_state["status"] = "failed"
        finally:
            reset_trace_sink(token)
            pending.put_nowait(None)
            await pump_task
        run, _ = await persist_run(session, run_uuid, query_text, final_state)

    # After persist_run, so a subscriber that sees "done" can fetch the finished run.
    await redis.xadd(stream, {"done": run.status})
    await redis.expire(stream, TRACE_STREAM_TTL_SECONDS)
    return {"run_id": run_id, "status": run.status}


async def startup(ctx: dict) -> None:
    ctx["redis"] = queue.redis


settings_dict = {
    "queue": queue,
    "functions": [run_query_task],
    "startup": startup,
    "concurrency": 4,
}
