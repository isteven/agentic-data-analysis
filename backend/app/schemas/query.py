from pydantic import BaseModel


class QueryRequest(BaseModel):
    query: str


class TraceStep(BaseModel):
    node_name: str
    step_type: str
    content: str


class QueryResponse(BaseModel):
    run_id: str
    status: str
    report_markdown: str | None = None
    trace: list[TraceStep] = []
