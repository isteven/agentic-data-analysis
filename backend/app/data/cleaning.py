"""Cleaning applied at ingest, before rows are stored and profiled. Only file-shape
fixes live here (a year taken from the manifest for files that have none); which rows
are totals or overlaps is inferred from the data (app/data/structure.py)."""

import pandas as pd


def clean_dataset(df: pd.DataFrame, entry: dict) -> pd.DataFrame:
    # MOM sheets carry their year only in the file/manifest, not as a column
    if "year" not in df.columns and entry.get("year") is not None:
        df = df.assign(year=entry["year"])

    return df
