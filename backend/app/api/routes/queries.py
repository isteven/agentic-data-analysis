import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.rate_limit import limit_queries
from app.core.config import get_settings
from app.db.session import get_session
from app.schemas.query import Analysis, QueryRequest, QueryResponse, TokenUsage, TraceStep
from app.services.query_service import create_run, get_llm_calls, get_run, mark_run_failed
from app.worker import queue

logger = logging.getLogger(__name__)

router = APIRouter()


def _to_response(run, trace_events: list[dict], llm_calls: list[dict] | None = None) -> QueryResponse:
    # run.token_usage is written when the run finishes; None means still running, or a
    # run from before token usage was recorded.
    token_usage = (
        TokenUsage(**run.token_usage, per_call=llm_calls or []) if run.token_usage else None
    )
    return QueryResponse(
        run_id=str(run.id),
        query_text=run.query_text,
        status=run.status,
        provider_used=run.provider_used,
        report_markdown=run.report_markdown,
        trace=[TraceStep(**event) for event in trace_events],
        analysis=Analysis(**run.chart_specs) if run.chart_specs else None,
        token_usage=token_usage,
    )


@router.post(
    "/api/queries",
    response_model=QueryResponse,
    status_code=202,
    dependencies=[Depends(limit_queries)],
)
async def submit_query(
    body: QueryRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> QueryResponse:
    """Creates the run (status "running") and hands it to the worker; the graph itself
    runs out-of-request in run_query_task (app/worker.py). Poll GET /api/queries/{run_id}
    or stream GET /api/agent-trace/{run_id} (SSE) for the result."""
    run_id = uuid.uuid4()
    run = await create_run(session, run_id, body.query, body.provider)
    try:
        await queue.enqueue(
            "run_query_task",
            run_id=str(run_id),
            query_text=body.query,
            provider=body.provider,
            timeout=get_settings().query_job_timeout_seconds,
            # A timed-out job is a completed run, marked failed by run_query_task's own
            # CancelledError handler - not a transient error worth silently re-running the
            # whole (expensive, multi-LLM-call) pipeline for.
            retries=0,
        )
    except Exception as exc:
        # The run row already exists: end it, or it shows as running forever.
        logger.exception("[DEBUG] submit_query: enqueue failed run_id=%s", run_id)
        await mark_run_failed(session, run_id, "The query couldn't be queued. Please try again.")
        raise HTTPException(
            status_code=503, detail="The query queue is unavailable. Please try again shortly."
        ) from exc
    response.headers["Location"] = f"/api/queries/{run_id}"
    return _to_response(run, [])


@router.get("/api/queries/{run_id}", response_model=QueryResponse)
async def get_query(run_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> QueryResponse:
    found = await get_run(session, run_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Run not found")
    run, trace_events = found
    return _to_response(run, trace_events, await get_llm_calls(session, run_id))
