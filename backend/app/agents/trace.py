import logging
from collections.abc import Callable
from contextvars import ContextVar, Token

from app.agents.state import AgentState, TraceEvent

logger = logging.getLogger(__name__)

# Agent steps can be long (SQL, tool output); logs keep the start.
LOGGED_CONTENT_CHARS = 1000

# Set by the worker for the duration of a run, so every event reaches the live stream
# the moment a node emits it - including each tool call inside the planner, which would
# otherwise only surface when the whole node finishes. Unset (None) on other paths.
_sink: ContextVar[Callable[[TraceEvent], None] | None] = ContextVar("trace_sink", default=None)


def set_trace_sink(sink: Callable[[TraceEvent], None] | None) -> Token:
    return _sink.set(sink)


def reset_trace_sink(token: Token) -> None:
    _sink.reset(token)


def emit_trace(state: AgentState, node_name: str, step_type: str, content: str) -> None:
    event: TraceEvent = {"node_name": node_name, "step_type": step_type, "content": content}
    state["trace_events"].append(event)
    logger.info(
        "agent step",
        extra={"node_name": node_name, "step_type": step_type, "content": content[:LOGGED_CONTENT_CHARS]},
    )
    sink = _sink.get()
    if sink is not None:
        sink(event)


def trace_stream_key(run_id: str) -> str:
    """Redis Stream holding a run's live trace. A stream rather than pub/sub: a
    subscriber that connects late replays from the start instead of missing events."""
    return f"agent-trace:{run_id}"


# How long a finished run's stream is kept for late subscribers; after that the SSE
# route replays the trace from the agent_traces table instead.
TRACE_STREAM_TTL_SECONDS = 3600
