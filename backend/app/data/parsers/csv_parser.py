import pandas as pd

# '-'/'na' mean suppressed/unavailable, not zero - must become NaN, not 0.
SENTINEL_VALUES = ["-", "na", "NA", "n.a.", "N.A.", ""]


def read_csv(path: str) -> pd.DataFrame:
    return pd.read_csv(path, na_values=SENTINEL_VALUES, keep_default_na=True)
