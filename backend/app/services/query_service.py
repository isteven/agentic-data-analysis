import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graph import build_graph
from app.agents.state import clear_dataframes, new_state
from app.models.agent_trace import AgentTrace
from app.models.analysis_run import AnalysisRun, AnalysisRunDataset
from app.models.dataset import Dataset
from app.models.finding import Finding


async def run_query(session: AsyncSession, query_text: str) -> tuple[AnalysisRun, list[dict]]:
    run_id = uuid.uuid4()
    state = new_state(query=query_text, run_id=str(run_id))

    graph = build_graph(session)
    try:
        final_state = await graph.ainvoke(state)
        # status column is varchar(16) - keep values short
        status = "completed" if not final_state.get("errors") else "partial"
    except Exception as exc:  # noqa: BLE001 - unrecoverable graph failure, degrade gracefully
        final_state = state
        final_state["errors"].append({"node_name": "graph", "message": str(exc)})
        status = "failed"
    finally:
        clear_dataframes(str(run_id))

    run = AnalysisRun(
        id=run_id,
        query_text=query_text,
        provider_used="openai",
        status=status,
        report_markdown=final_state.get("report_markdown"),
    )
    session.add(run)
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
