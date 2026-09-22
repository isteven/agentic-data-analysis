from typing import Any, TypedDict


class PlanStep(TypedDict):
    dataset_id: str
    reason: str


class RawExtract(TypedDict):
    dataset_id: str
    row_count: int
    columns: list[str]
    source_mode: str  # "file" | "live" | "file_fallback"


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


class AgentState(TypedDict):
    query: str
    run_id: str
    plan: list[PlanStep]
    raw_extracts: list[RawExtract]
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
        findings=[],
        report_markdown=None,
        grounded=None,
        trace_events=[],
        errors=[],
    )


# module-level, per-run dataframe store keyed by (run_id, dataset_id) - kept out of
# AgentState since LangGraph state should stay JSON-serializable; only lightweight
# metadata (RawExtract) goes into state itself.
_dataframe_store: dict[str, dict[str, Any]] = {}


def store_dataframe(run_id: str, dataset_id: str, df: Any) -> None:
    _dataframe_store.setdefault(run_id, {})[dataset_id] = df


def get_dataframe(run_id: str, dataset_id: str) -> Any | None:
    return _dataframe_store.get(run_id, {}).get(dataset_id)


def clear_dataframes(run_id: str) -> None:
    _dataframe_store.pop(run_id, None)
