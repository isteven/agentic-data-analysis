import json

import numpy as np
import pandas as pd

from app.data.profiler import MAX_LISTED_VALUES, profile_dataframe


def _by_column(profile: list[dict]) -> dict[str, dict]:
    return {c["column"]: c for c in profile}


def _sample_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "year": [2020, 2020, 2021, 2021],
            "industry": ["manufacturing", "construction", "manufacturing", None],
            "retrench": [100.0, np.nan, 80.0, 50.0],
        }
    )


def test_roles_are_inferred_from_data():
    cols = _by_column(profile_dataframe(_sample_df(), {}))

    assert cols["year"]["role"] == "time"
    assert cols["industry"]["role"] == "dimension"
    assert cols["retrench"]["role"] == "measure"


def test_time_column_records_range():
    cols = _by_column(profile_dataframe(_sample_df(), {}))

    assert (cols["year"]["min"], cols["year"]["max"]) == (2020, 2021)


def test_measure_records_range_and_null_share():
    retrench = _by_column(profile_dataframe(_sample_df(), {}))["retrench"]

    assert (retrench["min"], retrench["max"]) == (50.0, 100.0)
    assert retrench["null_pct"] == 0.25


def test_small_dimension_lists_all_distinct_values_sorted():
    industry = _by_column(profile_dataframe(_sample_df(), {}))["industry"]

    assert industry["distinct"] == 2
    assert industry["values"] == ["construction", "manufacturing"]


def test_large_dimension_stores_sample_not_full_list():
    df = pd.DataFrame({"degree": [f"degree {i}" for i in range(MAX_LISTED_VALUES + 50)]})

    degree = _by_column(profile_dataframe(df, {}))["degree"]

    assert degree["distinct"] == MAX_LISTED_VALUES + 50
    assert "values" not in degree
    assert len(degree["sample_values"]) < MAX_LISTED_VALUES


def test_numbers_outside_year_range_are_measures_not_time():
    df = pd.DataFrame({"count": [5, 12, 3000]})

    assert _by_column(profile_dataframe(df, {}))["count"]["role"] == "measure"


def test_manifest_column_meta_overrides_and_enriches():
    column_meta = {
        "retrench": {"type": "numeric", "unit": "persons", "additive": True, "description": "x"},
        "industry": {"role": "dimension"},
    }

    cols = _by_column(profile_dataframe(_sample_df(), {"column_meta": column_meta}))

    assert cols["retrench"]["additive"] is True
    assert cols["retrench"]["unit"] == "persons"
    assert cols["retrench"]["description"] == "x"


def test_manifest_role_override_wins():
    column_meta = {"year": {"role": "dimension"}}

    cols = _by_column(profile_dataframe(_sample_df(), {"column_meta": column_meta}))

    assert cols["year"]["role"] == "dimension"


def test_profile_is_json_serialisable():
    profile = profile_dataframe(_sample_df(), {})

    json.dumps(profile)  # must not raise on numpy / NaN values
