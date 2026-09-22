from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.query import QueryRequest, QueryResponse, TraceStep
from app.services.query_service import run_query

router = APIRouter()


@router.post("/api/queries", response_model=QueryResponse)
async def submit_query(
    body: QueryRequest,
    session: AsyncSession = Depends(get_session),
) -> QueryResponse:
    run, trace_events = await run_query(session, body.query)
    return QueryResponse(
        run_id=str(run.id),
        status=run.status,
        report_markdown=run.report_markdown,
        trace=[TraceStep(**event) for event in trace_events],
    )
