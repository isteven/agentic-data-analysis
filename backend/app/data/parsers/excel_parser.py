import openpyxl
import pandas as pd

HEADER_ROW = 7
DATA_START_ROW = 8


def read_mom_hours_sheet(path: str, sheet_name: str) -> pd.DataFrame:
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb[sheet_name]

    header_cells = next(ws.iter_rows(min_row=HEADER_ROW, max_row=HEADER_ROW, values_only=True))
    occupations = [str(c).strip() for c in header_cells[2:] if c is not None]

    records = []
    sex = None
    for row in ws.iter_rows(min_row=DATA_START_ROW, values_only=True):
        if row[0] is None and row[1] is None:
            break  # first fully-blank row marks the footer boundary
        if row[0] is not None:
            sex = str(row[0]).strip()
        hours_bucket = str(row[1]).strip()
        for occupation, value in zip(occupations, row[2 : 2 + len(occupations)]):
            records.append(
                {
                    "sex": sex,
                    "hours_bucket": hours_bucket,
                    "occupation": occupation,
                    "value": value,
                }
            )

    df = pd.DataFrame.from_records(records)
    df["value"] = df["value"].replace("-", pd.NA)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df
