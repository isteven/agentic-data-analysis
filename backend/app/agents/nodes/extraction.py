import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import AgentState, store_dataframe
from app.agents.trace import emit_trace
from app.data.api_client import fetch_datastore
from app.data.cleaning import clean_dataset
from app.data.manifest import load_manifest
from app.data.parsers.csv_parser import read_csv
from app.data.parsers.excel_parser import read_mom_hours_sheet
from app.models.dataset import Dataset

NODE_NAME = "extraction"


async def _load_from_file(session: AsyncSession, dataset_id: str, entry: dict) -> pd.DataFrame:
    """Reads a dataset from its seeded Postgres record + local file. Used both for
    mode: file datasets and as the fallback path for mode: api datasets whose live
    fetch failed (the fallback file is seeded into Postgres the same way, see
    seed_datasets.py's _has_seedable_file)."""
    dataset_row = await session.scalar(select(Dataset).where(Dataset.dataset_key == dataset_id))
    if dataset_row is None or dataset_row.raw_cache_path is None:
        raise RuntimeError(f"'{dataset_id}' has not been seeded yet.")

    if entry["format"] == "csv":
        return read_csv(dataset_row.raw_cache_path)
    if entry["format"] == "xlsx":
        return read_mom_hours_sheet(dataset_row.raw_cache_path, entry["sheet_name"])
    raise NotImplementedError(f"Format '{entry['format']}' not supported")


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

        mode = entry.get("mode")

        if mode not in ("file", "api"):
            emit_trace(
                state, NODE_NAME, "observation",
                f"'{dataset_id}' has unrecognized mode={mode} - skipping.",
            )
            state["errors"].append(
                {"node_name": NODE_NAME, "message": f"Unrecognized mode for '{dataset_id}': {mode}"}
            )
            continue

        df: pd.DataFrame | None = None
        source_mode = "file"

        if mode == "api":
            emit_trace(state, NODE_NAME, "action", f"Querying live API for '{dataset_id}'.")
            try:
                df = await fetch_datastore(entry["resource_id"])
                source_mode = "live"
                emit_trace(
                    state, NODE_NAME, "observation",
                    f"Live fetch succeeded for '{dataset_id}': {len(df)} rows.",
                )
            except Exception as exc:  # noqa: BLE001 - fall back to file below, don't propagate
                emit_trace(
                    state, NODE_NAME, "observation",
                    f"Live fetch failed for '{dataset_id}' ({exc}); "
                    f"{'falling back to cached file.' if entry.get('api_fallback') == 'file' else 'no fallback configured.'}",
                )
                if entry.get("api_fallback") != "file":
                    state["errors"].append(
                        {
                            "node_name": NODE_NAME,
                            "message": f"Live fetch failed for '{dataset_id}' and no fallback is configured: {exc}",
                        }
                    )
                    continue
                mode = "file"  # fall through to the shared file-loading path below
                source_mode = "file_fallback"

        if mode == "file":
            if df is None:  # not already loaded live above
                emit_trace(state, NODE_NAME, "action", f"Loading '{dataset_id}' from database record.")
            try:
                if df is None:
                    df = await _load_from_file(session, dataset_id, entry)
            except Exception as exc:  # noqa: BLE001 - per-source isolation, continue with other sources
                emit_trace(state, NODE_NAME, "observation", f"Failed to load '{dataset_id}': {exc}")
                state["errors"].append({"node_name": NODE_NAME, "message": str(exc)})
                continue

        df = clean_dataset(df, entry)
        store_dataframe(state["run_id"], dataset_id, df)
        state["raw_extracts"].append(
            {
                "dataset_id": dataset_id,
                "row_count": len(df),
                "columns": list(df.columns),
                "source_mode": source_mode,
            }
        )
        emit_trace(
            state, NODE_NAME, "observation",
            f"Loaded '{dataset_id}' ({source_mode}): {len(df)} rows, columns: {', '.join(df.columns)}.",
        )

    return state
