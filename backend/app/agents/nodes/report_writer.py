import math

from app.agents.llm import node_model
from app.agents.state import AgentState, task_question
from app.agents.trace import emit_trace

NODE_NAME = "report_writer"

# At least this many significant digits survive rounding, so a rounded number stays far
# inside the validator's 1% tolerance.
SIGNIFICANT_DIGITS = 6


def format_number(value) -> str:
    """How a result value is shown to the LLM, which copies numbers as it sees them. The
    views type every measure as double precision, so a head count arrives as 26110.0."""
    if not isinstance(value, float) or not math.isfinite(value):
        return str(value)
    if value.is_integer():
        return str(int(value))
    magnitude = math.floor(math.log10(abs(value)))
    decimals = max(2, SIGNIFICANT_DIGITS - 1 - magnitude)
    return f"{value:.{decimals}f}".rstrip("0").rstrip(".")


def _format_findings(findings: list[dict]) -> str:
    if not findings:
        return "(no findings computed)"
    lines = []
    for f in findings:
        lines.append(
            f"- {f['metric_name']} = {format_number(f['value'])} (source: {f['dataset_id']}, field: {f['field_ref']})"
        )
    return "\n".join(lines)


def _format_analysis(analysis: dict | None) -> str:
    if not analysis or not analysis.get("sql"):
        return "(no query result)"
    header = " | ".join(analysis["columns"])
    rows = "\n".join(" | ".join(format_number(v) for v in row) for row in analysis["rows"][:50])
    more = "\n(result truncated)" if analysis.get("truncated") else ""
    return (
        f"How the question was understood: {analysis.get('interpretation')}\n"
        f"Query: {analysis['sql']}\n"
        f"Result:\n{header}\n{rows}{more}"
    )


def _format_errors(errors: list[dict]) -> str:
    if not errors:
        return "(none)"
    return "\n".join(f"- [{e['node_name']}] {e['message']}" for e in errors)


def _review_note(state: AgentState) -> str:
    """The reviewer's reason when it sent the previous draft back (nodes/reviewer.py)."""
    if state.get("review_next") == NODE_NAME and state.get("review_feedback"):
        return f"A reviewer rejected your previous draft: {state['review_feedback']} Fix this.\n\n"
    return ""


async def report_writer_node(state: AgentState) -> AgentState:
    emit_trace(
        state, NODE_NAME, "reasoning", "Synthesizing findings into a natural-language report."
    )

    model = node_model(state, NODE_NAME, "quality")
    prompt = (
        "You are a policy data analyst writing a report for a researcher. You are given "
        "a list of pre-computed, grounded findings (numbers already calculated from real "
        "government data) and a list of any data-access issues encountered. Write a clear "
        "answer to the user's question using ONLY these findings - do not invent numbers. "
        "Cite the source dataset for every number you mention. If findings are missing or "
        "incomplete for part of the question, say so explicitly rather than guessing. "
        "Say briefly how the question was interpreted. Keep numbers as given (you may "
        "round), and give units where the data states them. The app shows a chart and "
        "the result table next to your report, so never say you can't provide a chart.\n\n"
        f"{_review_note(state)}"
        f"User question: {state['query']}\n"
        f"Interpreted as (state this reading in the report): {task_question(state)}\n\n"
        f"Query result (computed by the database):\n{_format_analysis(state.get('analysis'))}\n\n"
        f"Findings:\n{_format_findings(state['findings'])}\n\n"
        f"Data-access issues:\n{_format_errors(state['errors'])}"
    )

    response = await model.ainvoke(prompt)
    state["report_markdown"] = response.content

    emit_trace(state, NODE_NAME, "action", "Report drafted.")
    return state
