import logging
from collections.abc import Awaitable, Callable
from functools import partial

from langgraph.graph import END, START, StateGraph
from sqlalchemy.ext.asyncio import AsyncEngine

from app.agents.nodes.analytics import analytics_node
from app.agents.nodes.coordinator import coordinator_node
from app.agents.nodes.extraction import extraction_node
from app.agents.nodes.intent import intent_node, route_after_intent
from app.agents.nodes.report_writer import report_writer_node
from app.agents.nodes.reviewer import reviewer_node, route_after_review
from app.agents.nodes.validator import validator_node
from app.agents.state import AgentState
from app.agents.trace import emit_trace
from app.db.session import SessionFactory
from app.db.session import engine as default_engine

logger = logging.getLogger(__name__)

Node = Callable[[AgentState], Awaitable[AgentState]]


def guarded(node_name: str, node: Node) -> Node:
    """Error boundary for one graph step: a failure is logged, recorded as the step's
    error and shown in the trace, and the run carries on with what's already done.

    Without it one late failure (e.g. both LLM providers down at the reviewer) threw
    away a finished report and failed the whole run. Cancellation (a job timeout) is a
    BaseException, not an Exception, so it still stops the run.
    """

    async def run(state: AgentState) -> AgentState:
        try:
            return await node(state)
        except Exception as exc:  # the boundary's job; logged with its stack
            logger.exception("[DEBUG] node=%s run_id=%s failed", node_name, state.get("run_id"))
            message = f"{type(exc).__name__}: {exc}"
            state["errors"].append({"node_name": node_name, "message": message})
            emit_trace(
                state,
                node_name,
                "observation",
                f"Step failed ({message}); continuing with what was done so far.",
            )
            return state

    return run


def build_graph(session_factory: SessionFactory, engine: AsyncEngine = default_engine):
    graph = StateGraph(AgentState)
    nodes: dict[str, Node] = {
        "intent": partial(intent_node, session_factory=session_factory),
        "coordinator": coordinator_node,
        "extraction": partial(extraction_node, session_factory=session_factory),
        "analytics": partial(analytics_node, session_factory=session_factory, engine=engine),
        "report_writer": report_writer_node,
        "validator": validator_node,
        "reviewer": partial(reviewer_node, session_factory=session_factory),
    }
    for name, node in nodes.items():
        graph.add_node(name, guarded(name, node))

    graph.add_edge(START, "intent")
    # A question no dataset could answer ends here, before any dataset or SQL work.
    graph.add_conditional_edges(
        "intent", route_after_intent, {"coordinator": "coordinator", "end": END}
    )
    graph.add_edge("coordinator", "extraction")
    graph.add_edge("extraction", "analytics")
    graph.add_edge("analytics", "report_writer")
    graph.add_edge("report_writer", "validator")
    graph.add_edge("validator", "reviewer")
    # The reviewer sends a failed answer back to the step that caused it (at most
    # MAX_REVIEW_ROUNDS times); the rerun flows forward through the same checks.
    graph.add_conditional_edges(
        "reviewer",
        route_after_review,
        {"analytics": "analytics", "report_writer": "report_writer", "end": END},
    )

    return graph.compile()
