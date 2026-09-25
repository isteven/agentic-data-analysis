import json
import uuid

from saq import Queue

from app.agents.graph import build_graph
from app.agents.state import new_state
from app.agents.trace import trace_channel
from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.services.query_service import persist_run

settings = get_settings()

queue = Queue.from_url(settings.redis_url, name="apda")


async def run_query_task(
    ctx: dict, *, run_id: str, query_text: str, provider: str | None = None
) -> dict:
    """Runs the agent graph via astream (ARCHITECTURE.md §2.4), publishing each new
    trace event to Redis pub/sub as it appears rather than waiting for the full run
    to finish."""
    redis = ctx["redis"]
    channel = trace_channel(run_id)
    run_uuid = uuid.UUID(run_id)

    async with AsyncSessionLocal() as session:
        graph = build_graph(session)
        state = new_state(query=query_text, run_id=run_id, provider=provider)

        seen = 0
        final_state = state
        try:
            async for step_state in graph.astream(state, stream_mode="values"):
                final_state = step_state
                events = final_state.get("trace_events", [])
                for event in events[seen:]:
                    await redis.publish(channel, json.dumps(event))
                seen = len(events)
            final_state["status"] = "completed" if not final_state.get("errors") else "partial"
        except Exception as exc:  # noqa: BLE001 - unrecoverable graph failure, degrade gracefully
            final_state.setdefault("errors", []).append({"node_name": "graph", "message": str(exc)})
            final_state["status"] = "failed"
        run, _ = await persist_run(session, run_uuid, query_text, final_state)

    await redis.publish(channel, "__done__")
    return {"run_id": run_id, "status": run.status}


async def startup(ctx: dict) -> None:
    ctx["redis"] = queue.redis


settings_dict = {
    "queue": queue,
    "functions": [run_query_task],
    "startup": startup,
    "concurrency": 4,
}
