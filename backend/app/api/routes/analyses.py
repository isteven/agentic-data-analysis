from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.query import AnalysisListResponse, AnalysisSummary
from app.services.query_service import list_runs

router = APIRouter()


@router.get("/api/analyses", response_model=AnalysisListResponse)
async def get_analyses(session: AsyncSession = Depends(get_session)) -> AnalysisListResponse:
    """History list: most recent runs first. Full detail (report/trace/analysis) for
    one run is GET /api/queries/{run_id}, already built for polling."""
    runs = await list_runs(session)
    return AnalysisListResponse(
        runs=[
            AnalysisSummary(
                run_id=str(run.id),
                query_text=run.query_text,
                status=run.status,
                provider_used=run.provider_used,
                created_at=run.created_at,
                completed_at=run.completed_at,
            )
            for run in runs
        ]
    )
