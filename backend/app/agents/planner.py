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
from typing import Literal

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
    """Which result columns to chart. The chart type is picked by code from the
    result's shape (app/agents/chart.py), so the same kind of question always gets the
    same chart."""

    x: str | None = Field(
        default=None, description="Result column for the x axis: the time column for anything over time, else the category"
    )
    y: list[str] = Field(default_factory=list, description="Numeric result column(s) to plot")
    group: str | None = Field(
        default=None, description="Optional result column splitting rows into one series each"
    )
    best: Literal["lowest", "highest"] | None = Field(
        default=None,
        description=(
            "For a long list: which end the question is about - 'lowest' (shortest, cheapest, "
            "fewest) or 'highest' (top, most, longest). Only the first rows of a long list "
            "are charted, sorted this way."
        ),
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
- Answer at the level the question asks about. When it compares groups ("which university",
  "which industry") and a view has several rows per group (e.g. one per degree), reduce to one
  value per group first: AVG for measures that aren't summable (rates, means), SUM for
  summable ones. MAX, MIN or a single row stand for the group only when the question asks for
  the single best item ("which degree ..."). Say how you reduced in the interpretation (e.g.
  "average across its degrees, unweighted").
- When a measure comes in variants (an overall rate beside a narrower one, e.g. full-time
  only), use the general one unless the question names the narrower one.
- Never type a number from an earlier result into a query; the database computes every number.
- If a query is rejected, read the message and fix the query.
- Every answer is charted, so the final result must include the number(s) the answer rests
  on (e.g. the rate a ranking is based on), not only names.
- When the answer ranks or lists many items ("shortest", "highest", "top"), ORDER BY the
  measure it ranks by, best first, and set the chart's `best` to that end of the list.
- In submit_answer, say which result columns to chart (x, y, optional group); the chart
  type is chosen automatically. Chart one kind of measure at a time (counts or rates, not
  both), and include every series the question compares."""

# Sent with the question when the intent step found a span of periods.
TIME_RANGE_NOTE = (
    "The question covers {start}-{end}. Return one row per period in that range, with the "
    "time column, so the change can be seen and charted - not only the endpoints' difference."
)


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
    # What one row is, from the profile: answering "which university" from a view with a
    # row per degree needs a reduction per university, and saying so up front is what
    # makes that visible (hierarchy parents like <col>_level_1 don't add rows).
    keys = [c["column"] for c in catalog[view] if c["role"] in ("time", "dimension") and not c.get("level_of")]
    if keys:
        lines.append(f"Each row: one {' x '.join(keys)}.")
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
    time_range: dict | None = None,
) -> PlannerResult:
    """Answer `question` using only `views` (a subset of `catalog`).

    `time_range` ({"start", "end"} from the intent step): the question spans periods, so
    the answer should be one row per period. Enforced only on views that have a time
    column, and only once - an answer in the wrong shape still beats no answer.
    """
    visible = {v: catalog[v] for v in views if v in catalog}
    bound = model.bind_tools(TOOLS)
    overview = "\n\n".join(describe(v, visible) for v in visible)
    time_columns = sorted({c["column"] for cols in visible.values() for c in cols if c["role"] == "time"})
    wants_periods = bool(time_range and time_columns)
    prompt = f"Question: {question}\n\nViews selected for this question:\n{overview}"
    if wants_periods:
        prompt += "\n\n" + TIME_RANGE_NOTE.format(**time_range)
    messages = [
        SystemMessage(SYSTEM_PROMPT.format(views=", ".join(visible) or "(none)")),
        HumanMessage(prompt),
    ]
    outcome = PlannerResult(status="gave_up")
    sent_back_for_periods = False

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
                if (
                    wants_periods
                    and not sent_back_for_periods
                    and not any(c in result.columns for c in time_columns)
                ):
                    sent_back_for_periods = True
                    note = (
                        f"Sent back: the question covers {time_range['start']}-{time_range['end']}; "
                        f"return one row per period with the {' or '.join(time_columns)} column."
                    )
                    trace("observation", note)
                    messages.append(ToolMessage(note, tool_call_id=call["id"]))
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
