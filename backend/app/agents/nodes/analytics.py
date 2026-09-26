"""Analytics agent: the SQL planner (app/agents/planner.py) run as a graph node.

It answers the question over the views the extraction agent resolved, and turns the
submitted query's result into findings - the only numbers the report may use. Which
column is a label (year, sex, ...) and which is a value comes from the source views'
profiles, so nothing here knows any dataset.
"""

import logging
from functools import partial

import sqlglot
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlglot import exp

from app.agents.chart import build_chart_spec
from app.agents.llm import node_model
from app.agents.planner import run_planner
from app.agents.state import AgentState, task_question
from app.agents.trace import emit_trace
from app.data.manifest import load_manifest
from app.data.sql_runner import QueryResult, run_checked_sql
from app.data.views import VIEW_SCHEMA, load_view_catalog

logger = logging.getLogger(__name__)

NODE_NAME = "analytics"
MAX_FINDINGS = 200  # the report cites a handful; this only bounds a runaway result


def views_in(sql: str) -> list[str]:
    tree = sqlglot.parse_one(sql, read="postgres")
    seen: list[str] = []
    for table in tree.find_all(exp.Table):
        if table.db == VIEW_SCHEMA and table.name not in seen:
            seen.append(table.name)
    return seen


def findings_from_result(
    result: QueryResult,
    catalog: dict[str, list[dict]],
    view_members: dict[str, list[tuple[str, int | None]]],
) -> list[dict]:
    """One finding per numeric value in the result, labelled by the row's label columns.
    `view_members` is view -> [(dataset id, manifest year)]: a view built from one file
    per year cites the file for the row's year, not just the first file."""
    used = views_in(result.sql)
    label_columns = {
        c["column"] for v in used for c in catalog.get(v, []) if c["role"] in ("time", "dimension")
    }
    time_columns = {c["column"] for v in used for c in catalog.get(v, []) if c["role"] == "time"}
    labels = [i for i, name in enumerate(result.columns) if name in label_columns]
    base_views = [v.removesuffix("_totals") for v in used]
    members = next((view_members[v] for v in base_views if v in view_members), [])

    def cite(row: list) -> str | None:
        periods = {row[i] for i in labels if result.columns[i] in time_columns}
        by_year = next((d for d, year in members if year is not None and year in periods), None)
        return by_year or (members[0][0] if members else None)

    field_ref = ", ".join(f"{VIEW_SCHEMA}.{v}" for v in used)[:128]

    findings = []
    for row in result.rows:
        label = ", ".join(f"{result.columns[i]}={row[i]}" for i in labels)
        for i, value in enumerate(row):
            if i in labels or isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            name = f"{result.columns[i]} [{label}]" if label else result.columns[i]
            findings.append(
                {
                    "metric_name": name[:128],
                    "value": float(value),
                    "unit": None,
                    "dataset_id": cite(row),
                    "field_ref": field_ref,
                }
            )
            if len(findings) >= MAX_FINDINGS:
                return findings
    return findings


async def analytics_node(
    state: AgentState, session: AsyncSession, engine: AsyncEngine
) -> AgentState:
    manifest = load_manifest()
    year_of = {entry["id"]: entry.get("year") for entry in manifest}
    view_members: dict[str, list[tuple[str, int | None]]] = {}
    for extract in state["raw_extracts"]:
        view_members.setdefault(extract["view"], []).append(
            (extract["dataset_id"], year_of.get(extract["dataset_id"]))
        )
    if not view_members:
        emit_trace(
            state, NODE_NAME, "observation", "No usable data was extracted; nothing to analyse."
        )
        return state

    catalog = await load_view_catalog(session, manifest)
    views = [v for base in view_members for v in (base, f"{base}_totals") if v in catalog]

    question = task_question(state)
    previous = state.get("analysis") or {}
    if state.get("review_next") == NODE_NAME and state.get("review_feedback"):
        # Sent back by the reviewer: redo with its reason and the rejected query in view.
        question = (
            f"{question}\n\nA reviewer rejected the previous answer: "
            f"{state['review_feedback']}\nRejected query: {previous.get('sql')}"
        )
        state["findings"] = []
        state["errors"] = [e for e in state["errors"] if e["node_name"] != NODE_NAME]
        emit_trace(state, NODE_NAME, "reasoning", "Re-planning with the reviewer's feedback.")
    emit_trace(state, NODE_NAME, "reasoning", f"Planning a query over: {', '.join(views)}.")

    outcome = await run_planner(
        question=question,
        views=views,
        catalog=catalog,
        # Quality tier: the fast model ran out of steps on multi-step questions (a share
        # over two years), querying views by columns they don't have. Cost is secondary.
        model=node_model(state, NODE_NAME, "quality"),
        run_sql_fn=partial(run_checked_sql, engine, catalog=catalog),
        trace=lambda kind, content: emit_trace(state, NODE_NAME, kind, content),
    )
    result = outcome.result
    state["analysis"] = {
        "status": outcome.status,
        "interpretation": outcome.interpretation,
        "sql": result.sql if result else None,
        "columns": result.columns if result else [],
        "rows": result.rows if result else [],
        "truncated": result.truncated if result else False,
        "reason": outcome.reason,
        "chart": (
            build_chart_spec(outcome.chart_suggestion, result, catalog, views_in(result.sql))
            if result
            else None
        ),
    }

    if result is None:
        state["errors"].append(
            {
                "node_name": NODE_NAME,
                "message": outcome.reason or "The question couldn't be answered.",
            }
        )
        return state

    state["findings"] = findings_from_result(result, catalog, view_members)
    emit_trace(
        state,
        NODE_NAME,
        "observation",
        f"{len(state['findings'])} finding(s) from the final query "
        f"({outcome.steps} step(s), {outcome.queries_rejected} rejected).",
    )
    return state
