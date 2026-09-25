import pandas as pd

from app.data.cleaning import clean_dataset


def test_clean_dataset_adds_year_from_manifest_when_column_missing():
    df = pd.DataFrame({"sex": ["Total"], "value": [100.0]})

    cleaned = clean_dataset(df, {"id": "mom_2024", "year": 2024})

    assert cleaned["year"].tolist() == [2024]


def test_clean_dataset_leaves_existing_year_column_alone():
    df = pd.DataFrame({"year": [2020], "value": [1.0]})

    cleaned = clean_dataset(df, {"id": "x", "year": 1999})

    assert cleaned["year"].tolist() == [2020]
