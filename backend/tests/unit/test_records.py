import json

import numpy as np
import pandas as pd

from app.data.records import to_records


def test_records_are_json_native_with_missing_as_null():
    df = pd.DataFrame(
        {
            "year": np.array([2020, 2021], dtype="int64"),
            "industry": ["manufacturing", None],
            "retrench": [np.float64(100.5), np.nan],
        }
    )

    records = to_records(df)

    assert records == [
        {"year": 2020, "industry": "manufacturing", "retrench": 100.5},
        {"year": 2021, "industry": None, "retrench": None},
    ]
    json.dumps(records)  # must not raise


def test_pandas_na_becomes_null():
    df = pd.DataFrame({"value": pd.array([1.0, pd.NA], dtype="Float64")})

    assert to_records(df) == [{"value": 1.0}, {"value": None}]
