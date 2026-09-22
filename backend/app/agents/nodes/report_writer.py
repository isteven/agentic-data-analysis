from app.agents.state import AgentState
from app.agents.trace import emit_trace
from app.llm.provider_factory import get_chat_model

NODE_NAME = "report_writer"


def _format_findings(findings: list[dict]) -> str:
    if not findings:
        return "(no findings computed)"
    lines = []
    for f in findings:
        lines.append(
            f"- {f['metric_name']} = {f['value']} (source: {f['dataset_id']}, field: {f['field_ref']})"
        )
    return "\n".join(lines)


def _format_errors(errors: list[dict]) -> str:
    if not errors:
        return "(none)"
    return "\n".join(f"- [{e['node_name']}] {e['message']}" for e in errors)


async def report_writer_node(state: AgentState) -> AgentState:
    emit_trace(state, NODE_NAME, "reasoning", "Synthesizing findings into a natural-language report.")

    model = get_chat_model(model_tier="quality")
    prompt = (
        "You are a policy data analyst writing a report for a researcher. You are given "
        "a list of pre-computed, grounded findings (numbers already calculated from real "
        "government data) and a list of any data-access issues encountered. Write a clear "
        "answer to the user's question using ONLY these findings - do not invent numbers. "
        "Cite the source dataset for every number you mention. If findings are missing or "
        "incomplete for part of the question, say so explicitly rather than guessing.\n\n"
        f"User question: {state['query']}\n\n"
        f"Findings:\n{_format_findings(state['findings'])}\n\n"
        f"Data-access issues:\n{_format_errors(state['errors'])}"
    )

    response = await model.ainvoke(prompt)
    state["report_markdown"] = response.content

    emit_trace(state, NODE_NAME, "action", "Report drafted.")
    return state
