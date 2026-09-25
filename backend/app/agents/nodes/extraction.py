"""Extraction agent: turns the coordinator's dataset choices into queryable views.

Rows were parsed, cleaned and stored at ingest (scripts/seed_datasets.py), so nothing is
re-parsed per question. This node checks each chosen dataset is actually stored, maps
it to its typed view(s), and reports what the data-quality step did to it - totals and
overlapping values excluded, unverified periods left out, which measures may be summed -
so the trace shows the quality checks the numbers rest on.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import AgentState
from app.agents.trace import emit_trace
from app.data.manifest import load_manifest
from app.data.views import view_name_for
from app.models.dataset import Dataset
from app.models.dataset_record import DatasetRecord

NODE_NAME = "extraction"


def quality_summary(profile: list[dict]) -> str:
    """One line per fact the ingest step inferred, for the trace."""
    notes = []
    for c in profile:
        if c.get("exclude_values"):
            notes.append(
                f"{c['column']}: excluded {', '.join(c['exclude_values'])} (totals/overlaps)"
            )
        if c.get("parents"):
            notes.append(f"{c['column']}: {c.get('levels', 1)}-level hierarchy, lowest level kept")
        if c.get("unverified_periods"):
            spans = ", ".join(f"{lo}-{hi}" for lo, hi in c["unverified_periods"])
            notes.append(f"{c['column']}: periods {spans} left out (classification not verifiable)")
        if c.get("null_pct"):
            notes.append(f"{c['column']}: {c['null_pct']:.0%} missing")
    summable = [c["column"] for c in profile if c["role"] == "measure" and c.get("additive")]
    other = [c["column"] for c in profile if c["role"] == "measure" and not c.get("additive")]
    if summable:
        notes.append(f"summable: {', '.join(summable)}")
    if other:
        notes.append(f"not summable: {', '.join(other)}")
    return "; ".join(notes) or "no issues found"


async def extraction_node(state: AgentState, session: AsyncSession) -> AgentState:
    manifest_by_id = {entry["id"]: entry for entry in load_manifest()}

    for step in state["plan"]:
        dataset_id = step["dataset_id"]
        entry = manifest_by_id.get(dataset_id)
        if entry is None:
            emit_trace(
                state, NODE_NAME, "observation", f"Unknown dataset id '{dataset_id}' - skipped."
            )
            state["errors"].append(
                {"node_name": NODE_NAME, "message": f"Unknown dataset id: {dataset_id}"}
            )
            continue

        emit_trace(state, NODE_NAME, "action", f"Checking stored data for '{dataset_id}'.")
        dataset = await session.scalar(select(Dataset).where(Dataset.dataset_key == dataset_id))
        row_count = 0
        if dataset is not None:
            row_count = await session.scalar(
                select(func.count())
                .select_from(DatasetRecord)
                .where(DatasetRecord.dataset_id == dataset.id)
            )
        if not row_count:
            message = f"'{dataset_id}' has no stored data (not seeded, or its file is missing)."
            emit_trace(state, NODE_NAME, "observation", message)
            state["errors"].append({"node_name": NODE_NAME, "message": message})
            continue

        view = view_name_for(entry)
        profile = dataset.schema_profile or []
        state["raw_extracts"].append(
            {
                "dataset_id": dataset_id,
                "row_count": row_count,
                "columns": [c["column"] for c in profile],
                "source_mode": "stored",
                "view": view,
            }
        )
        emit_trace(
            state,
            NODE_NAME,
            "observation",
            f"'{dataset_id}': {row_count} rows, queried as data.{view}. "
            f"Quality checks: {quality_summary(profile)}.",
        )

    return state
