"""Quality review (ARCHITECTURE.md §3.2): an LLM judge after the number check.

The validator proves the report's numbers match the query result; it can't tell when
the query answered a different question (e.g. averaging a head-count column and
calling it "average hours"). The reviewer reads what each queried column means and
sends a failure back to the step that caused it, with the reason as feedback.
"""

import json
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.llm import node_model
from app.agents.nodes.analytics import views_in
from app.agents.planner import describe
from app.agents.state import AgentState
from app.agents.trace import emit_trace
from app.data.manifest import load_manifest
from app.data.views import load_view_catalog

NODE_NAME = "reviewer"
MAX_REVIEW_ROUNDS = 1  # re-routes per run: bounds cost at one extra planner/writer pass
REVIEW_ROWS = 20


class Review(BaseModel):
    verdict: Literal["pass", "wrong_analysis", "poor_report"] = Field(
        description=(
            "pass: the result answers the question and the report describes it correctly. "
            "wrong_analysis: the query computes something other than what was asked "
            "(wrong measure, wrong grain, wrong filter, a column misread). "
            "poor_report: the query is right but the report misdescribes it or doesn't "
            "answer the question."
        )
    )
    reason: str = Field(
        description="One or two sentences: what is wrong and what should be done instead."
    )


def _format_result(analysis: dict) -> str:
    rows = "\n".join(json.dumps(r, default=str) for r in analysis["rows"][:REVIEW_ROWS])
    more = (
        f"\n({len(analysis['rows']) - REVIEW_ROWS} more rows)"
        if len(analysis["rows"]) > REVIEW_ROWS
        else ""
    )
    return f"{json.dumps(analysis['columns'])}\n{rows}{more}"


async def reviewer_node(state: AgentState, session: AsyncSession) -> AgentState:
    state["review_next"] = None
    analysis = state.get("analysis") or {}
    if not analysis.get("sql"):
        # Nothing was computed (declined or failed upstream): nothing to judge.
        return state

    catalog = await load_view_catalog(session, load_manifest())
    columns = "\n\n".join(describe(v, catalog) for v in views_in(analysis["sql"]) if v in catalog)

    emit_trace(
        state, NODE_NAME, "reasoning", "Checking the answer actually addresses the question."
    )
    model = node_model(state, NODE_NAME, "fast").with_structured_output(Review)
    review: Review = await model.ainvoke(
        "You review a data analysis before it reaches a policy researcher. Judge meaning, "
        "not arithmetic: the numbers were computed by the database and already checked "
        "against the report. Use the column descriptions to spot a column used for "
        "something it doesn't measure. Pass anything that reasonably answers the question; "
        "fail only a clear mismatch.\n\n"
        f"Question: {state['query']}\n\n"
        f"Columns queried:\n{columns}\n\n"
        f"How the analyst understood the question: {analysis.get('interpretation')}\n"
        f"SQL:\n{analysis['sql']}\n\n"
        f"Result:\n{_format_result(analysis)}\n\n"
        f"Report:\n{state.get('report_markdown') or '(none)'}"
    )

    if review.verdict == "pass":
        emit_trace(state, NODE_NAME, "observation", "Passed: the answer addresses the question.")
        return state

    if state["review_rounds"] >= MAX_REVIEW_ROUNDS:
        emit_trace(
            state,
            NODE_NAME,
            "observation",
            f"Still flagged after {MAX_REVIEW_ROUNDS} retry ({review.verdict}): {review.reason} "
            "Keeping the answer with a caveat.",
        )
        state["report_markdown"] = (
            f"{state.get('report_markdown') or ''}\n\n---\n*Reviewer's caveat: {review.reason}*"
        )
        return state

    target = "analytics" if review.verdict == "wrong_analysis" else "report_writer"
    state["review_rounds"] += 1
    state["review_feedback"] = review.reason
    state["review_next"] = target
    emit_trace(
        state,
        NODE_NAME,
        "action",
        f"Sent back to {target} ({review.verdict}): {review.reason}",
    )
    return state


def route_after_review(state: AgentState) -> str:
    return state.get("review_next") or "end"
