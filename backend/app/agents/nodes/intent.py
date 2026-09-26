"""Intent (ARCHITECTURE.md §3.2): rewrite the question into one precise reading before
any planning, and decline questions no dataset could answer.

Without it the same ambiguous wording was read differently run to run: "the share of
women working 60+ hours" came back as a share of employed women in one run and as a
share of all workers in the next. Fixing the reading once, up front, makes every later
step (dataset choice, SQL, review) work on the same question.
"""

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.llm import node_model
from app.agents.state import AgentState
from app.agents.trace import emit_trace
from app.data.manifest import load_manifest
from app.data.views import load_view_catalog, view_name_for

NODE_NAME = "intent"


class TimeRange(BaseModel):
    start: int = Field(description="First period (year) the question covers")
    end: int = Field(description="Last period (year) the question covers")


class Intent(BaseModel):
    rewritten: str = Field(
        description=(
            "The question restated as one precise, unambiguous analytical question, in the "
            "same language. Keep the user's subject, measures, groups and years; resolve "
            "vague wording rather than adding new scope."
        )
    )
    answerable: bool = Field(
        description="False only when no listed dataset could plausibly help answer it."
    )
    reason: str | None = Field(default=None, description="If not answerable: why, in one sentence.")
    # Read from the question's meaning, not from keywords: "since 2015", "between 2020 and
    # 2023", "over the past 3 years" and "2023 vs 2025" all span periods. The planner
    # then returns one row per period, so the answer can be charted over time.
    time_range: TimeRange | None = Field(
        default=None,
        description=(
            "Set when the question looks at a change, trend or comparison across a span of "
            "periods: the first and last year it covers. Open-ended and relative spans "
            "(\"since 2015\", \"the last five years\") end at the latest year the relevant "
            "dataset covers, and count back from it. None when it asks about a single "
            "period or no time at all."
        ),
    )


# A dimension with at most this many values is listed with them. Without the values the
# model can't tell a band or category exists: it declined "how many worked 60+ hours" as
# not in the data, though a "60 Hours & Over" band is. Larger ones (degrees, stations)
# stay names only, to keep the prompt small.
MAX_LISTED_VALUES = 12


def _dimension(column: dict) -> str:
    values = column.get("values") or []
    distinct = column.get("distinct") or len(values)
    if values and distinct <= MAX_LISTED_VALUES:
        return f"{column['column']} ({', '.join(str(v) for v in values)})"
    return column["column"]


def _catalog(manifest: list[dict], views: dict[str, list[dict]]) -> str:
    """Title, years covered and what each dataset measures (measures with their
    descriptions, dimension names) - enough to tell "not in the data" from "worded
    differently in the data", which titles alone weren't."""
    lines, seen = [], set()
    for entry in manifest:
        view = view_name_for(entry)
        if view in seen:
            continue
        seen.add(view)
        years = next(
            (f"{c.get('min')}-{c.get('max')}" for c in views.get(view, []) if c["role"] == "time"),
            "no time dimension",
        )
        title = entry["title"].split(",")[0] if entry.get("group") else entry["title"]
        columns = views.get(view, [])
        measures = "; ".join(
            f"{c['column']}" + (f" ({c['description']})" if c.get("description") else "")
            for c in columns
            if c["role"] == "measure"
        )
        dimensions = ", ".join(
            _dimension(c) for c in columns if c["role"] == "dimension" and not c.get("level_of")
        )
        lines.append(f"- {title}; years: {years}; measures: {measures}; by: {dimensions or '-'}")
    return "\n".join(lines)


async def intent_node(state: AgentState, session: AsyncSession) -> AgentState:
    manifest = load_manifest()
    views = await load_view_catalog(session, manifest)

    emit_trace(state, NODE_NAME, "reasoning", "Restating the question precisely before planning.")
    # Quality tier: deciding what a question means (and whether the data covers it) is
    # a judgement call; the fast model kept rewording or refusing answerable questions.
    model = node_model(state, NODE_NAME, "quality").with_structured_output(Intent)
    intent: Intent = await model.ainvoke(
        "Restate a policy researcher's question so every analyst would compute the same "
        "thing. Change as little as possible: most questions are already precise and "
        "should come back nearly word for word. Rules:\n"
        "- Keep the kind of answer asked for. A count stays a count, a total stays a "
        "total. Never turn a question into a share, rate, incidence or percentage unless "
        "the user asked for one.\n"
        "- Only when the user asks for a share, rate or percentage OF a group, make the "
        "denominator explicit: \"the share of X doing Y\" means, among X, the percentage "
        "doing Y (not X-doing-Y as a share of everyone). If the wording could still fairly "
        "be read against two different groups, don't pick one: ask for both, each with its "
        "denominator named, so the answer is the same whoever reads it.\n"
        "- Resolve relative time (\"latest\", \"past 3 years\", \"recently\") to concrete "
        "years using the coverage listed below.\n"
        "- When the question ranks or compares groups (e.g. which university) and the "
        "dataset breaks each group down further (its \"by\" list has finer columns, e.g. "
        "degree within university), say how a group's value is formed: averaged across "
        "its parts for a rate or mean, summed for a count. Leave it alone when the user "
        "asks for the single best item (e.g. which degree).\n"
        "- Keep the user's words for the measure: a \"share\" stays a share, a \"count\" a "
        "count. Only the subject may be swapped for its exact synonym in the data "
        "(\"layoffs\" -> retrenchment) - never for a different, merely related "
        "one. If what the user asks about isn't what any dataset measures, set "
        "answerable=false - don't answer a nearby question instead.\n"
        "- Answerable means computable, not \"a column is named for it\": a count, total, "
        "average or share that can be worked out from a dataset's columns (counting the "
        "distinct values of a column, adding up the bands of a head-count measure) is "
        "answerable. Decline only when the subject itself is in no dataset.\n"
        "- Don't answer it; don't add groups, measures or years the user didn't ask about.\n\n"
        f"Datasets:\n{_catalog(manifest, views)}\n\n"
        f"Question: {state['query']}"
    )

    if not intent.answerable:
        reason = intent.reason or "None of the available datasets cover this question."
        state["errors"].append({"node_name": NODE_NAME, "message": reason})
        state["report_markdown"] = (
            f"This question can't be answered from the available datasets. {reason}"
        )
        emit_trace(state, NODE_NAME, "observation", f"Declined: {reason}")
        return state

    state["intent_query"] = intent.rewritten
    emit_trace(state, NODE_NAME, "action", f"Interpreted as: {intent.rewritten}")
    if intent.time_range:
        state["time_range"] = intent.time_range.model_dump()
        emit_trace(
            state,
            NODE_NAME,
            "observation",
            f"Covers {intent.time_range.start}-{intent.time_range.end}: answer per period.",
        )
    return state


def route_after_intent(state: AgentState) -> str:
    return "coordinator" if state.get("intent_query") else "end"
