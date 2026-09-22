import re

import pandas as pd

from app.agents.state import AgentState, get_dataframe
from app.agents.trace import emit_trace

NODE_NAME = "analytics"

# Columns treated as numeric metrics to aggregate, in priority order, per known dataset shape.
_NUMERIC_METRIC_CANDIDATES = ["retrench", "job_vacancy", "value"]


def _find_query_filters(query: str, df: pd.DataFrame) -> dict[str, str]:
    """Match query words against unique values of categorical (object) columns."""
    filters: dict[str, str] = {}
    query_lower = query.lower()
    for col in df.select_dtypes(include="object").columns:
        for value in df[col].dropna().unique():
            value_str = str(value)
            if len(value_str) < 3:
                continue
            if re.search(re.escape(value_str.lower()), query_lower):
                filters[col] = value_str
                break
    return filters


def _pick_metric_column(df: pd.DataFrame) -> str | None:
    for candidate in _NUMERIC_METRIC_CANDIDATES:
        if candidate in df.columns:
            return candidate
    numeric_cols = df.select_dtypes(include="number").columns
    for col in numeric_cols:
        if col != "year":
            return col
    return None


def _analyze_dataset(dataset_id: str, df: pd.DataFrame, query: str, state: AgentState) -> None:
    filters = _find_query_filters(query, df)
    filtered_df = df
    for col, value in filters.items():
        filtered_df = filtered_df[filtered_df[col] == value]

    filter_desc = ", ".join(f"{k}={v}" for k, v in filters.items()) or "no specific filter matched"
    emit_trace(
        state, NODE_NAME, "reasoning",
        f"Analyzing '{dataset_id}': {filter_desc}; {len(filtered_df)} rows in scope.",
    )

    if filtered_df.empty:
        emit_trace(state, NODE_NAME, "observation", f"No matching rows in '{dataset_id}' after filtering.")
        return

    metric_col = _pick_metric_column(filtered_df)
    if metric_col is None:
        emit_trace(state, NODE_NAME, "observation", f"No numeric metric column found in '{dataset_id}'.")
        return

    if "year" in filtered_df.columns:
        by_year = (
            filtered_df.groupby("year")[metric_col].sum(min_count=1).dropna().sort_index()
        )
        for year, value in by_year.items():
            state["findings"].append(
                {
                    "metric_name": f"{metric_col}_{filter_desc or 'total'}_{year}",
                    "value": float(value),
                    "unit": None,
                    "dataset_id": dataset_id,
                    "field_ref": f"{metric_col} (year={year}, {filter_desc})",
                }
            )
        if len(by_year) >= 2:
            first_year, last_year = by_year.index[0], by_year.index[-1]
            delta = float(by_year.iloc[-1] - by_year.iloc[0])
            state["findings"].append(
                {
                    "metric_name": f"{metric_col}_change_{first_year}_to_{last_year}",
                    "value": delta,
                    "unit": None,
                    "dataset_id": dataset_id,
                    "field_ref": f"{metric_col} trend {first_year}->{last_year} ({filter_desc})",
                }
            )
        emit_trace(
            state, NODE_NAME, "observation",
            f"Computed {len(by_year)} year(s) of '{metric_col}' for '{dataset_id}'.",
        )
    else:
        total = filtered_df[metric_col].sum(min_count=1)
        if pd.notna(total):
            state["findings"].append(
                {
                    "metric_name": f"{metric_col}_{filter_desc or 'total'}",
                    "value": float(total),
                    "unit": None,
                    "dataset_id": dataset_id,
                    "field_ref": f"{metric_col} ({filter_desc})",
                }
            )
        emit_trace(state, NODE_NAME, "observation", f"Computed total '{metric_col}' for '{dataset_id}'.")


async def analytics_node(state: AgentState) -> AgentState:
    for extract in state["raw_extracts"]:
        dataset_id = extract["dataset_id"]
        df = get_dataframe(state["run_id"], dataset_id)
        if df is None:
            continue
        _analyze_dataset(dataset_id, df, state["query"], state)

    return state
