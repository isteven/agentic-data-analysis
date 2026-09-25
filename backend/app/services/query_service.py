import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graph import build_graph
from app.agents.state import new_state
from app.core.config import get_settings
from app.models.agent_trace import AgentTrace
from app.models.analysis_run import AnalysisRun, AnalysisRunDataset
from app.models.dataset import Dataset
from app.models.finding import Finding


async def execute_graph(
    session: AsyncSession, query_text: str, run_id: uuid.UUID, provider: str | None = None
) -> dict:
    state = new_state(query=query_text, run_id=str(run_id), provider=provider)

    graph = build_graph(session)
    try:
        final_state = await graph.ainvoke(state)
        # status column is varchar(16) - keep values short
        final_state["status"] = "completed" if not final_state.get("errors") else "partial"
    except Exception as exc:  # noqa: BLE001 - unrecoverable graph failure, degrade gracefully
        final_state = state
        final_state["errors"].append({"node_name": "graph", "message": str(exc)})
        final_state["status"] = "failed"
    return final_state


async def create_run(
    session: AsyncSession, run_id: uuid.UUID, query_text: str, provider: str | None
) -> AnalysisRun:
    """Row created at submit time (status "running"), before the graph runs, so a
    poll or the history page can find the run immediately - not just once it
    finishes (ARCHITECTURE.md §9.1)."""
    run = AnalysisRun(
        id=run_id,
        query_text=query_text,
        provider_used=provider or get_settings().llm_default_provider,
        status="running",
    )
    session.add(run)
    await session.commit()
    return run


async def persist_run(
    session: AsyncSession, run_id: uuid.UUID, query_text: str, final_state: dict
) -> tuple[AnalysisRun, list[dict]]:
    run = await session.get(AnalysisRun, run_id)
    if run is None:
        # Fallback for a run never created via create_run() (e.g. the old synchronous
        # path, or a test) - insert rather than update.
        run = AnalysisRun(id=run_id, query_text=query_text)
        session.add(run)

    run.provider_used = _provider_used(final_state)
    run.status = final_state["status"]
    run.report_markdown = final_state.get("report_markdown")
    # the query result + chart spec: what the dashboard draws, kept for history
    run.chart_specs = final_state.get("analysis")
    await session.flush()

    dataset_ids_used = {extract["dataset_id"] for extract in final_state.get("raw_extracts", [])}
    if dataset_ids_used:
        dataset_rows = await session.scalars(
            select(Dataset).where(Dataset.dataset_key.in_(dataset_ids_used))
        )
        key_to_id = {row.dataset_key: row.id for row in dataset_rows}

        for finding in final_state.get("findings", []):
            dataset_pk = key_to_id.get(finding["dataset_id"])
            if dataset_pk is None:
                continue
            session.add(
                Finding(
                    run_id=run_id,
                    dataset_id=dataset_pk,
                    metric_name=finding["metric_name"],
                    value=finding["value"],
                    unit=finding["unit"],
                    field_ref=finding["field_ref"],
                )
            )

        for dataset_pk in key_to_id.values():
            session.add(AnalysisRunDataset(run_id=run_id, dataset_id=dataset_pk))

    trace_events = final_state.get("trace_events", [])
    for event in trace_events:
        session.add(
            AgentTrace(
                run_id=run_id,
                node_name=event["node_name"],
                step_type=event["step_type"],
                content=event["content"],
            )
        )

    await session.commit()
    return run, trace_events


def _provider_used(final_state: dict) -> str:
    """Requested provider, plus any switch, e.g. "openai->bedrock" (column is varchar(32))."""
    used = final_state.get("provider") or get_settings().llm_default_provider
    switches = sorted(set(final_state.get("fallbacks", [])))
    return (", ".join(switches) if switches else used)[:32]


async def run_query(
    session: AsyncSession, query_text: str, provider: str | None = None
) -> tuple[AnalysisRun, list[dict]]:
    """Synchronous path: runs the graph in-request and persists in one call. Superseded
    by create_run() + the worker task + persist_run() for the real API route, but kept
    for anything that wants a one-shot result without Redis/a worker (tests, scripts)."""
    run_id = uuid.uuid4()
    final_state = await execute_graph(session, query_text, run_id, provider)
    return await persist_run(session, run_id, query_text, final_state)


async def get_run(session: AsyncSession, run_id: uuid.UUID) -> tuple[AnalysisRun, list[dict]] | None:
    """For GET /api/queries/{run_id}: polling fallback while a run is still `running`,
    or to fetch it after the fact (SSE dropped, or the client reconnects)."""
    run = await session.get(AnalysisRun, run_id)
    if run is None:
        return None
    trace_rows = await session.scalars(
        select(AgentTrace).where(AgentTrace.run_id == run_id).order_by(AgentTrace.created_at)
    )
    trace_events = [
        {"node_name": t.node_name, "step_type": t.step_type, "content": t.content} for t in trace_rows
    ]
    return run, trace_events
