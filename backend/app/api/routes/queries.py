import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.query import Analysis, QueryRequest, QueryResponse, TraceStep
from app.services.query_service import create_run, get_run
from app.worker import queue

router = APIRouter()


def _to_response(run, trace_events: list[dict]) -> QueryResponse:
    return QueryResponse(
        run_id=str(run.id),
        status=run.status,
        provider_used=run.provider_used,
        report_markdown=run.report_markdown,
        trace=[TraceStep(**event) for event in trace_events],
        analysis=Analysis(**run.chart_specs) if run.chart_specs else None,
    )


@router.post("/api/queries", response_model=QueryResponse, status_code=202)
async def submit_query(
    body: QueryRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> QueryResponse:
    """Creates the run (status "running") and hands it to the worker; the graph itself
    runs out-of-request in run_query_task (app/worker.py). Poll GET /api/queries/{run_id}
    or stream GET /api/agent-trace/{run_id} (SSE, planned) for the result."""
    run_id = uuid.uuid4()
    run = await create_run(session, run_id, body.query, body.provider)
    await queue.enqueue(
        "run_query_task", run_id=str(run_id), query_text=body.query, provider=body.provider
    )
    response.headers["Location"] = f"/api/queries/{run_id}"
    return _to_response(run, [])


@router.get("/api/queries/{run_id}", response_model=QueryResponse)
async def get_query(run_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> QueryResponse:
    found = await get_run(session, run_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return _to_response(*found)
