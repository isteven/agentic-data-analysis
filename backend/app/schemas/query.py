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
    status: str
    report_markdown: str | None = None
    trace: list[TraceStep] = []
    analysis: Analysis | None = None
