import pandas as pd


def _to_native(value):
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    return value.item() if hasattr(value, "item") else value


def to_records(df: pd.DataFrame) -> list[dict]:
    """One JSON-safe document per row: missing values become null, numpy scalars become
    plain Python, so rows can be stored in `dataset_records.record` (JSONB)."""
    return [{k: _to_native(v) for k, v in row.items()} for row in df.to_dict("records")]
