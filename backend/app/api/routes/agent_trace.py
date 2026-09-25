"""GET /api/agent-trace/{run_id}: the run's agent trace as Server-Sent Events.

Events: `trace` (one TraceEvent as JSON), then a final `done` (the run's status).
Reads the run's Redis Stream from the start, so a client that connects late still
gets every step; falls back to the agent_traces table once the stream has expired.
"""

import json
import logging
import time
import uuid

import redis.asyncio as aioredis
from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sse_starlette.sse import EventSourceResponse

from app.agents.trace import trace_stream_key
from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.models.agent_trace import AgentTrace
from app.models.analysis_run import AnalysisRun

logger = logging.getLogger(__name__)
router = APIRouter()

TERMINAL_STATUSES = {"completed", "partial", "failed"}
BLOCK_MS = 2000  # wait per read; between reads the run's status is re-checked
# A worker that dies mid-run never writes "done"; don't hold the connection forever.
MAX_STREAM_SECONDS = 600


async def _run_status(run_id: uuid.UUID) -> str | None:
    async with AsyncSessionLocal() as session:
        run = await session.get(AnalysisRun, run_id)
        return run.status if run else None


async def _persisted_trace(run_id: uuid.UUID) -> list[dict]:
    async with AsyncSessionLocal() as session:
        rows = await session.scalars(
            select(AgentTrace).where(AgentTrace.run_id == run_id).order_by(AgentTrace.created_at)
        )
        return [
            {"node_name": t.node_name, "step_type": t.step_type, "content": t.content}
            for t in rows
        ]


@router.get("/api/agent-trace/{run_id}")
async def stream_agent_trace(run_id: uuid.UUID) -> EventSourceResponse:
    if await _run_status(run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found")

    key = trace_stream_key(str(run_id))

    async def events():
        client = aioredis.from_url(get_settings().redis_url, decode_responses=True)
        last_id = "0"
        deadline = time.monotonic() + MAX_STREAM_SECONDS
        try:
            while time.monotonic() < deadline:
                batch = await client.xread({key: last_id}, block=BLOCK_MS, count=100)
                for _, entries in batch:
                    for entry_id, fields in entries:
                        last_id = entry_id
                        if "done" in fields:
                            yield {"event": "done", "data": fields["done"]}
                            return
                        yield {"event": "trace", "data": fields["event"]}
                if batch:
                    continue

                # Nothing new this interval. If the run finished and its stream is gone
                # (expired, or the run predates streaming), replay from the database.
                status = await _run_status(run_id)
                if status in TERMINAL_STATUSES and not await client.exists(key):
                    if last_id == "0":
                        for event in await _persisted_trace(run_id):
                            yield {"event": "trace", "data": json.dumps(event)}
                    yield {"event": "done", "data": status}
                    return

            logger.warning("[DEBUG] trace stream timed out run_id=%s", run_id)
            yield {"event": "done", "data": await _run_status(run_id) or "failed"}
        finally:
            await client.aclose()

    return EventSourceResponse(events())
