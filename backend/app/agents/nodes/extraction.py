from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import AgentState, store_dataframe
from app.agents.trace import emit_trace
from app.data.manifest import load_manifest
from app.data.parsers.csv_parser import read_csv
from app.data.parsers.excel_parser import read_mom_hours_sheet
from app.models.dataset import Dataset

NODE_NAME = "extraction"


async def extraction_node(state: AgentState, session: AsyncSession) -> AgentState:
    manifest_by_id = {entry["id"]: entry for entry in load_manifest()}

    for step in state["plan"]:
        dataset_id = step["dataset_id"]
        entry = manifest_by_id.get(dataset_id)

        if entry is None:
            emit_trace(
                state, NODE_NAME, "observation",
                f"Coordinator selected unknown dataset id '{dataset_id}' - skipping.",
            )
            state["errors"].append(
                {"node_name": NODE_NAME, "message": f"Unknown dataset id: {dataset_id}"}
            )
            continue

        if entry.get("mode") != "file":
            emit_trace(
                state, NODE_NAME, "observation",
                f"'{dataset_id}' is mode={entry.get('mode')} - live extraction for this "
                "mode isn't implemented yet, so this source will be skipped.",
            )
            state["errors"].append(
                {
                    "node_name": NODE_NAME,
                    "message": (
                        f"'{dataset_id}' requires live API extraction, which is not yet "
                        "built. This source was skipped; the answer may be incomplete."
                    ),
                }
            )
            continue

        emit_trace(state, NODE_NAME, "action", f"Loading '{dataset_id}' from database record.")

        try:
            dataset_row = await session.scalar(
                select(Dataset).where(Dataset.dataset_key == dataset_id)
            )
            if dataset_row is None or dataset_row.raw_cache_path is None:
                raise RuntimeError(f"'{dataset_id}' has not been seeded yet.")

            if entry["format"] == "csv":
                df = read_csv(dataset_row.raw_cache_path)
            elif entry["format"] == "xlsx":
                df = read_mom_hours_sheet(dataset_row.raw_cache_path, entry["sheet_name"])
            else:
                raise NotImplementedError(f"Format '{entry['format']}' not supported")

            store_dataframe(state["run_id"], dataset_id, df)
            state["raw_extracts"].append(
                {
                    "dataset_id": dataset_id,
                    "row_count": len(df),
                    "columns": list(df.columns),
                }
            )
            emit_trace(
                state, NODE_NAME, "observation",
                f"Loaded '{dataset_id}': {len(df)} rows, columns: {', '.join(df.columns)}.",
            )
        except Exception as exc:  # noqa: BLE001 - per-source isolation, continue with other sources
            emit_trace(state, NODE_NAME, "observation", f"Failed to load '{dataset_id}': {exc}")
            state["errors"].append({"node_name": NODE_NAME, "message": str(exc)})

    return state
