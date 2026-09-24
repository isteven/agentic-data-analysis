import pandas as pd

from app.data.cleaning import apply_default_slice, clean_dataset


def test_clean_dataset_drops_rows_before_min_year():
    df = pd.DataFrame({"year": [2004, 2005, 2006, 2007], "retrench": [1, 2, 3, 4]})

    cleaned = clean_dataset(df, {"id": "x", "min_year": 2006})

    assert cleaned["year"].tolist() == [2006, 2007]


def test_clean_dataset_adds_year_from_manifest_when_column_missing():
    df = pd.DataFrame({"sex": ["Total"], "value": [100.0]})

    cleaned = clean_dataset(df, {"id": "mom_2024", "year": 2024})

    assert cleaned["year"].tolist() == [2024]


def test_clean_dataset_leaves_existing_year_column_alone():
    df = pd.DataFrame({"year": [2020], "value": [1.0]})

    cleaned = clean_dataset(df, {"id": "x", "year": 1999})

    assert cleaned["year"].tolist() == [2020]


def test_default_slice_keeps_only_listed_values_for_unfiltered_column():
    df = pd.DataFrame(
        {
            "industry": ["manufacturing", "electronic products", "construction"],
            "retrench": [100, 60, 50],
        }
    )
    entry = {"default_slice": {"industry": ["manufacturing", "construction"]}}

    sliced = apply_default_slice(df, entry, filtered_columns=set())

    assert sliced["industry"].tolist() == ["manufacturing", "construction"]


def test_default_slice_skips_columns_the_query_filtered_on():
    df = pd.DataFrame({"industry": ["electronic products"], "retrench": [60]})
    entry = {"default_slice": {"industry": ["manufacturing", "construction"]}}

    sliced = apply_default_slice(df, entry, filtered_columns={"industry"})

    assert sliced["industry"].tolist() == ["electronic products"]


def test_default_slice_ignores_columns_not_in_dataframe():
    df = pd.DataFrame({"year": [2020], "retrench": [1]})
    entry = {"default_slice": {"industry": ["manufacturing"]}}

    sliced = apply_default_slice(df, entry, filtered_columns=set())

    assert len(sliced) == 1


def test_default_slice_is_noop_without_manifest_rule():
    df = pd.DataFrame({"industry": ["a", "b"], "retrench": [1, 2]})

    sliced = apply_default_slice(df, {}, filtered_columns=set())

    assert len(sliced) == 2
