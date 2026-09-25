"""The planner: a ReAct agent that answers a question by writing SQL over the data views.

Reason -> Act -> Observe, with tools that only read: it can describe a view, look at
sample rows and run exploratory queries, then commits by submitting one final query.
Every query, exploratory or final, goes through the SQL gate and the read-only runner
(app/data/sql_gate.py, sql_runner.py), and a rejection comes back as an observation the
planner can fix - that retry loop is the "checked SQL" of ARCHITECTURE.md §3.2, done as
agent steps rather than a separate graph edge.

The planner decides what to compute; the database computes it. Numbers reported later
come only from the submitted query's result, never from the model's own text.

Dependencies (model, SQL runner, catalog) are passed in, so the loop is unit-testable
with a scripted model and a fake runner.
"""

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, Field

from app.data.sql_gate import SqlRejected
from app.data.sql_runner import QueryResult

logger = logging.getLogger(__name__)

MAX_STEPS = 8  # tool calls per question; bounds cost when the model goes in circles
OBSERVATION_ROWS = 30  # rows shown back to the model per query
MAX_LISTED_VALUES = 40

RunSql = Callable[[str], Awaitable[QueryResult]]
Trace = Callable[[str, str], None]  # (step_type, content)


# --- tools (schemas the model sees) --------------------------------------------------


# Lower-case class names: each class name is the tool name the model sees.
class describe_view(BaseModel):
    """Columns of a view: role (time / dimension / measure), whether a measure can be
    summed, units, value lists or ranges, and hierarchy level columns."""

    view: str = Field(description="View name without the 'data.' prefix")


class sample_rows(BaseModel):
    """A few raw rows of a view, to see what values look like."""

    view: str = Field(description="View name without the 'data.' prefix")
    limit: int = Field(default=5, ge=1, le=20)


class run_sql(BaseModel):
    """Run an exploratory read-only PostgreSQL SELECT over data.<view> views and see the
    result. Use it to check values, spot-check totals or try an approach."""

    sql: str


class ChartSuggestion(BaseModel):
    """How to show the final result; columns must be columns of the result."""

    type: str = Field(description="'line' (trend over time), 'bar' (compare categories) or 'none'")
    x: str | None = Field(default=None, description="Result column for the x axis")
    y: list[str] = Field(default_factory=list, description="Numeric result column(s) to plot")
    group: str | None = Field(
        default=None, description="Optional result column splitting rows into one series each"
    )


class submit_answer(BaseModel):
    """Commit the final query. Its result is the only source of numbers for the report,
    so it must return everything the answer needs, already aggregated."""

    sql: str
    interpretation: str = Field(
        description="One sentence: how the question was understood and what the query computes"
    )
    chart: ChartSuggestion | None = Field(default=None, description="How to chart the result")


class cannot_answer(BaseModel):
    """Stop because the available views can't answer the question."""

    reason: str


TOOLS = [describe_view, sample_rows, run_sql, submit_answer, cannot_answer]

SYSTEM_PROMPT = """You answer questions about government statistics by querying PostgreSQL views.

Work step by step: think, call one tool, read the result, repeat. Look before you commit:
describe the views you need, check values you filter on, then call submit_answer with one
final query that returns everything the answer needs. If the views can't answer the
question, call cannot_answer.

Rules:
- Views are read as data.<name>. Only these views exist: {views}.
- Only SELECT. Aggregate in SQL; keep results small (the final result is what the report cites).
- Never SUM a measure marked "not summable" (rates, means, medians); use AVG/MIN/MAX or per-row values.
- Rows in these views are safe to add up: totals and overlapping categories were removed.
  Where a column has a hierarchy, <column>_level_1 is the top level; GROUP BY it for totals by group.
- Filter values must match the listed values exactly (check with describe_view or run_sql).
- Growth rates: use LN / EXP, or (last / first - 1). Medians: percentile_cont(0.5) WITHIN GROUP (ORDER BY x).
- Shares and ratios ("share of X", "% of Y that ..."): compute the numerator and the denominator
  in ONE query over the same rows, with conditional aggregates, grouped by period, e.g.
  100.0 * SUM(m) FILTER (WHERE <dimension> = '<value>') / SUM(m). Apply the population filter
  (the group the share is of) in WHERE so it limits both parts. A <view>_totals view has only
  the time column and summed measures, no dimensions, so it can't be filtered by category.
- Never type a number from an earlier result into a query; the database computes every number.
- If a query is rejected, read the message and fix the query.
- In submit_answer, suggest a chart: 'line' for trends over time, 'bar' to compare
  categories, 'none' when a table reads better (e.g. a short ranked list). Chart one
  kind of measure at a time (counts or rates, not both), and include every series the
  question compares."""


@dataclass
class PlannerResult:
    status: str  # "answered" | "cannot_answer" | "gave_up"
    interpretation: str | None = None
    result: QueryResult | None = None
    reason: str | None = None
    chart_suggestion: dict | None = None
    steps: int = 0
    queries_rejected: int = 0
    tool_log: list[dict] = field(default_factory=list)


def describe(view: str, catalog: dict[str, list[dict]]) -> str:
    """The view's columns as the planner sees them: compact, one line per column."""
    lines = [f"data.{view}:"]
    for c in catalog[view]:
        role = c["role"]
        parts = [f"- {c['column']} ({role}"]
        if role == "measure":
            parts.append(", summable" if c.get("additive") else ", not summable")
        if c.get("unit"):
            parts.append(f", unit: {c['unit']}")
        parts.append(")")
        if c.get("description"):
            parts.append(f" {c['description']}.")
        if role == "time" or (role == "measure" and c.get("min") is not None):
            parts.append(f" range {c.get('min')}-{c.get('max')}.")
        if c.get("level_of"):
            parts.append(f" hierarchy level of {c['level_of']}; 1 = top.")
        values = c.get("values") or c.get("sample_values")
        if values and not c.get("level_of"):
            shown = values[:MAX_LISTED_VALUES]
            more = len(values) - len(shown) + max(0, (c.get("distinct") or 0) - len(values))
            parts.append(f" values: {json.dumps(shown)}")
            if more > 0:
                parts.append(f" (+{more} more; query DISTINCT to see them)")
        if c.get("unverified_periods"):
            parts.append(
                f" periods left out (unverified classification): {c['unverified_periods']}."
            )
        lines.append("".join(parts))
    return "\n".join(lines)


def _format_result(result: QueryResult, limit: int = OBSERVATION_ROWS) -> str:
    rows = result.rows[:limit]
    body = "\n".join(json.dumps(r, default=str) for r in rows)
    note = ""
    if len(result.rows) > limit or result.truncated:
        note = f"\n(showing {len(rows)} of {'500+' if result.truncated else len(result.rows)} rows)"
    return (
        f"columns: {json.dumps(result.columns)}\n{body}{note}"
        if rows
        else (f"columns: {json.dumps(result.columns)}\n(no rows)")
    )


async def run_planner(
    question: str,
    views: list[str],
    catalog: dict[str, list[dict]],
    model: BaseChatModel,
    run_sql_fn: RunSql,
    trace: Trace,
    max_steps: int = MAX_STEPS,
) -> PlannerResult:
    """Answer `question` using only `views` (a subset of `catalog`)."""
    visible = {v: catalog[v] for v in views if v in catalog}
    bound = model.bind_tools(TOOLS)
    overview = "\n\n".join(describe(v, visible) for v in visible)
    messages = [
        SystemMessage(SYSTEM_PROMPT.format(views=", ".join(visible) or "(none)")),
        HumanMessage(f"Question: {question}\n\nViews selected for this question:\n{overview}"),
    ]
    outcome = PlannerResult(status="gave_up")

    async def act(name: str, args: dict) -> str:
        if name == "describe_view":
            view = args.get("view", "").removeprefix("data.")
            return (
                describe(view, visible)
                if view in visible
                else f"No view '{view}'. Views: {list(visible)}"
            )
        if name == "sample_rows":
            view = args.get("view", "").removeprefix("data.")
            if view not in visible:
                return f"No view '{view}'. Views: {list(visible)}"
            limit = max(1, min(int(args.get("limit", 5)), 20))
            return _format_result(await run_sql_fn(f"SELECT * FROM data.{view} LIMIT {limit}"))
        if name == "run_sql":
            return _format_result(await run_sql_fn(args["sql"]))
        return f"Unknown tool '{name}'."

    nudged = False
    while outcome.steps < max_steps:
        response: AIMessage = await bound.ainvoke(messages)
        messages.append(response)
        if response.content and isinstance(response.content, str):
            trace("reasoning", response.content.strip())
        if not response.tool_calls:
            if nudged:
                break
            nudged = True
            messages.append(HumanMessage("Call a tool: explore, submit_answer or cannot_answer."))
            continue

        for call in response.tool_calls:
            outcome.steps += 1
            name, args = call["name"], call.get("args") or {}
            outcome.tool_log.append({"tool": name, "args": args})

            if name == "cannot_answer":
                trace("action", f"cannot_answer: {args.get('reason', '')}")
                outcome.status, outcome.reason = "cannot_answer", args.get("reason")
                return outcome

            if name == "submit_answer":
                trace(
                    "action",
                    f"submit_answer: {args.get('interpretation', '')}\n{args.get('sql', '')}",
                )
                try:
                    result = await run_sql_fn(args.get("sql", ""))
                except SqlRejected as exc:
                    outcome.queries_rejected += 1
                    trace("observation", f"Final query rejected: {exc}")
                    messages.append(ToolMessage(f"Rejected: {exc}", tool_call_id=call["id"]))
                    continue
                trace("observation", f"Final result: {len(result.rows)} row(s)")
                outcome.status = "answered"
                outcome.interpretation = args.get("interpretation")
                outcome.chart_suggestion = args.get("chart")
                outcome.result = result
                return outcome

            trace("action", f"{name}: {json.dumps(args)}")
            try:
                observation = await act(name, args)
            except SqlRejected as exc:
                outcome.queries_rejected += 1
                observation = f"Rejected: {exc}"
            except Exception as exc:  # a tool failure is an observation, not a crash
                logger.exception("[DEBUG] run_planner: tool %s failed", name)
                observation = f"Tool error: {exc}"
            trace("observation", observation)
            messages.append(ToolMessage(observation, tool_call_id=call["id"]))

    outcome.reason = f"No final query after {outcome.steps} step(s)."
    trace("observation", outcome.reason)
    return outcome
