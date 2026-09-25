from datetime import datetime

from pydantic import BaseModel

from app.llm.config import ProviderName


class QueryRequest(BaseModel):
    query: str
    provider: ProviderName | None = None  # None = server default (LLM_DEFAULT_PROVIDER)


class TraceStep(BaseModel):
    node_name: str
    step_type: str
    content: str


class ChartSpec(BaseModel):
    type: str  # line | bar | none
    x: str | None = None
    y: list[str] = []
    group: str | None = None
    source: str | None = None  # planner | fallback


class Analysis(BaseModel):
    """The database-computed result the report and chart are drawn from."""

    status: str
    interpretation: str | None = None
    sql: str | None = None
    columns: list[str] = []
    rows: list[list] = []
    truncated: bool = False
    reason: str | None = None
    chart: ChartSpec | None = None


class QueryResponse(BaseModel):
    run_id: str
    query_text: str
    status: str
    provider_used: str | None = None  # e.g. "openai", or "openai->bedrock" after a fallback
    report_markdown: str | None = None
    trace: list[TraceStep] = []
    analysis: Analysis | None = None


class AnalysisSummary(BaseModel):
    """One row in the history list - light on purpose; GET /api/queries/{run_id} has
    the full report/trace/analysis for the detail view."""

    run_id: str
    query_text: str
    status: str
    provider_used: str | None = None
    created_at: datetime
    completed_at: datetime | None = None


class AnalysisListResponse(BaseModel):
    runs: list[AnalysisSummary]
