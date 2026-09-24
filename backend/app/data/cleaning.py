"""Manifest-declared cleaning rules, shared by the seed script and query-time extraction
so both see the same rows. Rules are properties of the source data (see
DATA_SOURCES.md), declared per dataset in manifest.yaml rather than hardcoded here."""

import pandas as pd


def clean_dataset(df: pd.DataFrame, entry: dict) -> pd.DataFrame:
    # MOM sheets carry their year only in the file/manifest, not as a column
    if "year" not in df.columns and entry.get("year") is not None:
        df = df.assign(year=entry["year"])

    # e.g. retrenchment: industry x occupation classification changed pre-2006
    min_year = entry.get("min_year")
    if min_year is not None and "year" in df.columns:
        df = df[df["year"] >= min_year].reset_index(drop=True)

    return df


def apply_default_slice(df: pd.DataFrame, entry: dict, filtered_columns: set[str]) -> pd.DataFrame:
    """Several sources mix totals, parent categories and their sub-categories, or two
    classification schemes, in the same column - summing every row double-counts.
    For each column the query did NOT filter on, keep only the manifest's
    `default_slice` values: a non-overlapping set that covers the whole."""
    for column, values in (entry.get("default_slice") or {}).items():
        if column in filtered_columns or column not in df.columns:
            continue
        df = df[df[column].isin(values)]
    return df
