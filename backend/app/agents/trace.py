from app.agents.state import AgentState


def emit_trace(state: AgentState, node_name: str, step_type: str, content: str) -> None:
    state["trace_events"].append(
        {"node_name": node_name, "step_type": step_type, "content": content}
    )


def trace_channel(run_id: str) -> str:
    return f"agent-trace:{run_id}"
