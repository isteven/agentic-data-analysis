"""Describes each dataset's columns at ingest, so the query path can reason about any
dataset from its profile instead of hardcoded column names (see ARCHITECTURE.md §3.2)."""

import pandas as pd

# Enough to list every industry / occupation / university value in the current data
# (largest: 68 industries) while keeping prompts small; bigger columns get a sample.
MAX_LISTED_VALUES = 100
SAMPLE_SIZE = 20
YEAR_RANGE = (1900, 2100)

# Human-declared facts the data itself can't reveal (e.g. whether a measure may be summed).
_MANIFEST_FIELDS = ("role", "additive", "unit", "description")


def _to_native(value):
    if pd.isna(value):
        return None
    return value.item() if hasattr(value, "item") else value


def _infer_role(series: pd.Series) -> str:
    if not pd.api.types.is_numeric_dtype(series):
        return "dimension"
    values = series.dropna()
    looks_like_years = (
        not values.empty and (values == values.round()).all() and values.between(*YEAR_RANGE).all()
    )
    return "time" if looks_like_years else "measure"


def _profile_column(series: pd.Series) -> dict:
    role = _infer_role(series)
    profile: dict = {
        "column": str(series.name),
        "role": role,
        "dtype": "number" if pd.api.types.is_numeric_dtype(series) else "text",
        "null_pct": round(float(series.isna().mean()), 4),
    }
    values = series.dropna()

    if role in ("time", "measure"):
        profile["min"] = _to_native(values.min()) if not values.empty else None
        profile["max"] = _to_native(values.max()) if not values.empty else None
        if role == "time":
            profile["min"] = int(profile["min"]) if profile["min"] is not None else None
            profile["max"] = int(profile["max"]) if profile["max"] is not None else None
        return profile

    distinct = sorted({str(v) for v in values.unique()})
    profile["distinct"] = len(distinct)
    if len(distinct) <= MAX_LISTED_VALUES:
        profile["values"] = distinct
    else:
        profile["sample_values"] = distinct[:SAMPLE_SIZE]
    return profile


def profile_dataframe(df: pd.DataFrame, entry: dict) -> list[dict]:
    column_meta = entry.get("column_meta") or {}
    profiles = []
    for column in df.columns:
        profile = _profile_column(df[column])
        overrides = column_meta.get(column) or {}
        for field in _MANIFEST_FIELDS:
            if field in overrides:
                profile[field] = overrides[field]
        profiles.append(profile)
    return profiles
