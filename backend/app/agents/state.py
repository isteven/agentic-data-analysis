from typing import TypedDict


class PlanStep(TypedDict):
    dataset_id: str
    reason: str


class RawExtract(TypedDict):
    dataset_id: str
    row_count: int
    columns: list[str]
    source_mode: str  # "stored" (rows in dataset_records, read through its view)
    view: str


class TraceEvent(TypedDict):
    node_name: str
    step_type: str  # reasoning | action | observation
    content: str


class FindingDict(TypedDict):
    metric_name: str
    value: float | None
    unit: str | None
    dataset_id: str
    field_ref: str | None


class AgentError(TypedDict):
    node_name: str
    message: str


class Analysis(TypedDict):
    """The planner's committed query and its result - the only source of numbers."""

    status: str  # "answered" | "cannot_answer" | "gave_up"
    interpretation: str | None
    sql: str | None
    columns: list[str]
    rows: list[list]
    truncated: bool
    reason: str | None


class AgentState(TypedDict):
    query: str
    run_id: str
    plan: list[PlanStep]
    raw_extracts: list[RawExtract]
    analysis: Analysis | None
    findings: list[FindingDict]
    report_markdown: str | None
    grounded: bool | None
    trace_events: list[TraceEvent]
    errors: list[AgentError]


def new_state(query: str, run_id: str) -> AgentState:
    return AgentState(
        query=query,
        run_id=run_id,
        plan=[],
        raw_extracts=[],
        analysis=None,
        findings=[],
        report_markdown=None,
        grounded=None,
        trace_events=[],
        errors=[],
    )
