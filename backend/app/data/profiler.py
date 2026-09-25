"""Describes each dataset's columns at ingest, so the query path can reason about any
dataset from its profile instead of hardcoded column names (see ARCHITECTURE.md §3.2)."""

import pandas as pd

from app.data.structure import ancestor_chain, infer_structure, proves_additive

# Bump when the profile's content changes, so the seed re-profiles unchanged files
PROFILER_VERSION = 2

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


def _is_identifier_relabeling(numeric: pd.Series, other: pd.Series) -> bool:
    """True when `numeric` is just another spelling of `other` in the same rows (e.g. a
    postal code standing for a station name) - each value of one always pairs with
    exactly one value of the other, never a quantity's actual relationship to anything."""
    paired = pd.DataFrame({"a": numeric, "b": other}).dropna()
    if paired.empty:
        return False
    return (
        paired.groupby("a")["b"].nunique().eq(1).all()
        and paired.groupby("b")["a"].nunique().eq(1).all()
    )


def _infer_role(series: pd.Series, df: pd.DataFrame) -> str:
    if not pd.api.types.is_numeric_dtype(series):
        return "dimension"
    values = series.dropna()
    looks_like_years = (
        not values.empty and (values == values.round()).all() and values.between(*YEAR_RANGE).all()
    )
    if looks_like_years:
        return "time"
    for other_name in df.columns:
        other = df[other_name]
        is_candidate = other.name != series.name and not pd.api.types.is_numeric_dtype(other)
        if is_candidate and _is_identifier_relabeling(series, other):
            return "dimension"
    return "measure"


def _profile_column(series: pd.Series, df: pd.DataFrame) -> dict:
    role = _infer_role(series, df)
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


def _add_structure(df: pd.DataFrame, profiles: list[dict]) -> None:
    """Infer how each dimension's values nest / overlap (app/data/structure.py) and
    whether each measure may be summed. A measure counts as additive only when some
    column proves it (a parent equals the sum of its parts); unproven measures such as
    rates and medians default to non-additive, the safe side for SUM."""
    time_col = next((p["column"] for p in profiles if p["role"] == "time"), None)
    dimensions = [p for p in profiles if p["role"] == "dimension"]
    chosen: dict[str, dict] | None = None
    for measure in (p for p in profiles if p["role"] == "measure"):
        structures = {
            d["column"]: infer_structure(df, d["column"], measure["column"], time_col)
            for d in dimensions
        }
        measure["additive"] = any(proves_additive(s) for s in structures.values())
        if measure["additive"] and chosen is None:
            chosen = structures
    for d in dimensions:
        structure = (chosen or {}).get(d["column"])
        if structure:
            parents = structure["parents"]
            d.update(structure)
            d["levels"] = max((len(ancestor_chain(v, parents)) for v in parents), default=1)


def profile_dataframe(df: pd.DataFrame, entry: dict) -> list[dict]:
    column_meta = entry.get("column_meta") or {}
    profiles = [_profile_column(df[column], df) for column in df.columns]
    _add_structure(df, profiles)
    for profile in profiles:
        overrides = column_meta.get(profile["column"]) or {}
        for field in _MANIFEST_FIELDS:
            if field in overrides:
                profile[field] = overrides[field]
    return profiles
