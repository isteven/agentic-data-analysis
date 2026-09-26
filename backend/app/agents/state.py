from typing import TypedDict

from app.llm.usage import CallUsage


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


class LlmCall(CallUsage):
    """One LLM attempt, tagged with the node that made it (app/agents/llm.py)."""

    node_name: str
    tier: str  # fast | quality


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
    chart: dict | None  # app/agents/chart.py spec


class AgentState(TypedDict):
    query: str  # the user's words, as asked
    # The intent step's precise rewrite (nodes/intent.py); None = not rewritten.
    intent_query: str | None
    run_id: str
    provider: str | None  # requested provider; None = LLM_DEFAULT_PROVIDER
    fallbacks: list[str]  # "openai->bedrock" for each call that switched provider
    llm_calls: list[LlmCall]  # every LLM attempt with its provider-reported token usage
    plan: list[PlanStep]
    raw_extracts: list[RawExtract]
    analysis: Analysis | None
    findings: list[FindingDict]
    report_markdown: str | None
    grounded: bool | None
    trace_events: list[TraceEvent]
    errors: list[AgentError]
    # Quality review (nodes/reviewer.py): the latest verdict's reason, fed back to the
    # step being redone, and how many times the run has been sent back.
    review_feedback: str | None
    review_next: str | None  # "analytics" | "report_writer" | None (= finish)
    review_rounds: int


def new_state(query: str, run_id: str, provider: str | None = None) -> AgentState:
    return AgentState(
        query=query,
        intent_query=None,
        run_id=run_id,
        provider=provider,
        fallbacks=[],
        llm_calls=[],
        plan=[],
        raw_extracts=[],
        analysis=None,
        findings=[],
        report_markdown=None,
        grounded=None,
        trace_events=[],
        errors=[],
        review_feedback=None,
        review_next=None,
        review_rounds=0,
    )


def task_question(state: AgentState) -> str:
    """What the agents work on: the intent step's precise rewrite, else the user's words."""
    return state.get("intent_query") or state["query"]
