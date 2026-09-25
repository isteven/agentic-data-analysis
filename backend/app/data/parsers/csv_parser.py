import pandas as pd

# '-'/'na' mean suppressed/unavailable, not zero - must become NaN, not 0.
SENTINEL_VALUES = ["-", "na", "NA", "n.a.", "N.A.", ""]

# A digit string starting with 0 (e.g. postal code 039193) is a code, not a number:
# reading it as an integer silently turns it into a different code (39193).
_LEADING_ZERO_CODE = r"0\d+"


def _code_columns(path: str) -> list[str]:
    raw = pd.read_csv(path, dtype=str, na_values=SENTINEL_VALUES, keep_default_na=True)
    return [
        column
        for column in raw.columns
        if raw[column].dropna().str.strip().str.fullmatch(_LEADING_ZERO_CODE).any()
    ]


def read_csv(path: str) -> pd.DataFrame:
    return pd.read_csv(
        path,
        na_values=SENTINEL_VALUES,
        keep_default_na=True,
        dtype={column: str for column in _code_columns(path)},
    )
