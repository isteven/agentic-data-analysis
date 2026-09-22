from functools import partial

from langgraph.graph import END, START, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.nodes.analytics import analytics_node
from app.agents.nodes.coordinator import coordinator_node
from app.agents.nodes.extraction import extraction_node
from app.agents.nodes.report_writer import report_writer_node
from app.agents.nodes.validator import validator_node
from app.agents.state import AgentState


def build_graph(session: AsyncSession):
    graph = StateGraph(AgentState)

    graph.add_node("coordinator", coordinator_node)
    graph.add_node("extraction", partial(extraction_node, session=session))
    graph.add_node("analytics", analytics_node)
    graph.add_node("report_writer", report_writer_node)
    graph.add_node("validator", validator_node)

    graph.add_edge(START, "coordinator")
    graph.add_edge("coordinator", "extraction")
    graph.add_edge("extraction", "analytics")
    graph.add_edge("analytics", "report_writer")
    graph.add_edge("report_writer", "validator")
    graph.add_edge("validator", END)

    return graph.compile()
