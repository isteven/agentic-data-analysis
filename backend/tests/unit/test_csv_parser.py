import pandas as pd

from app.data.parsers.csv_parser import read_csv


def test_uppercase_na_marker_becomes_missing_and_column_stays_numeric(tmp_path):
    path = tmp_path / "ges.csv"
    path.write_text("year,gross_monthly_median\n2023,4500\n2023,N.A.\n2023,-\n")

    df = read_csv(str(path))

    assert pd.api.types.is_numeric_dtype(df["gross_monthly_median"])
    assert df["gross_monthly_median"].isna().sum() == 2
