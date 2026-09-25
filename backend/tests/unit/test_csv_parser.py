import pandas as pd

from app.data.parsers.csv_parser import read_csv


def test_uppercase_na_marker_becomes_missing_and_column_stays_numeric(tmp_path):
    path = tmp_path / "ges.csv"
    path.write_text("year,gross_monthly_median\n2023,4500\n2023,N.A.\n2023,-\n")

    df = read_csv(str(path))

    assert pd.api.types.is_numeric_dtype(df["gross_monthly_median"])
    assert df["gross_monthly_median"].isna().sum() == 2


def test_codes_with_a_leading_zero_stay_text(tmp_path):
    path = tmp_path / "stations.csv"
    path.write_text("postal_code,name,minutes\n039193,A,1.5\n189561,B,2.0\n")

    df = read_csv(str(path))

    assert df["postal_code"].tolist() == ["039193", "189561"]
    assert pd.api.types.is_numeric_dtype(df["minutes"])


def test_zero_and_decimals_below_one_are_still_numbers(tmp_path):
    path = tmp_path / "rates.csv"
    path.write_text("rate,count\n0,0\n0.5,10\n")

    df = read_csv(str(path))

    assert pd.api.types.is_numeric_dtype(df["rate"]) and pd.api.types.is_numeric_dtype(df["count"])
