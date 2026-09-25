from functools import partial

from langgraph.graph import END, START, StateGraph
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.agents.nodes.analytics import analytics_node
from app.agents.nodes.coordinator import coordinator_node
from app.agents.nodes.extraction import extraction_node
from app.agents.nodes.report_writer import report_writer_node
from app.agents.nodes.reviewer import reviewer_node, route_after_review
from app.agents.nodes.validator import validator_node
from app.agents.state import AgentState
from app.db.session import engine as default_engine


def build_graph(session: AsyncSession, engine: AsyncEngine = default_engine):
    graph = StateGraph(AgentState)

    graph.add_node("coordinator", coordinator_node)
    graph.add_node("extraction", partial(extraction_node, session=session))
    graph.add_node("analytics", partial(analytics_node, session=session, engine=engine))
    graph.add_node("report_writer", report_writer_node)
    graph.add_node("validator", validator_node)
    graph.add_node("reviewer", partial(reviewer_node, session=session))

    graph.add_edge(START, "coordinator")
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
