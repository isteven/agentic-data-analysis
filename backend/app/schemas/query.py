from pydantic import BaseModel


class QueryRequest(BaseModel):
    query: str


class QueryResponse(BaseModel):
    run_id: str
    status: str
    report_markdown: str | None = None
