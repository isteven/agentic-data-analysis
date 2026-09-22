import httpx
import pandas as pd
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from app.data.parsers.csv_parser import SENTINEL_VALUES

DATASTORE_SEARCH_URL = "https://data.gov.sg/api/action/datastore_search"
PAGE_LIMIT = 5000
MAX_PAGES = 10  # safety cap - known dataset sizes here are a few thousand rows


@retry(
    retry=retry_if_exception_type((httpx.TransportError, httpx.TimeoutException)),
    stop=stop_after_attempt(2),
    wait=wait_fixed(1),
    reraise=True,
)
async def _fetch_page(client: httpx.AsyncClient, resource_id: str, offset: int) -> dict:
    response = await client.get(
        DATASTORE_SEARCH_URL,
        params={"resource_id": resource_id, "limit": PAGE_LIMIT, "offset": offset},
        timeout=5.0,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("success"):
        raise RuntimeError(f"datastore_search returned success=false: {payload}")
    return payload["result"]


async def fetch_datastore(resource_id: str) -> pd.DataFrame:
    """Fetches all records for a data.gov.sg Datastore Search resource, paginating as
    needed, and returns them as a DataFrame with the same sentinel-handling convention
    (`-`/`na` -> NaN) as the file-based CSV parser. Raises on any failure - the caller
    is responsible for falling back to a cached file."""
    records: list[dict] = []
    offset = 0

    async with httpx.AsyncClient() as client:
        for _ in range(MAX_PAGES):
            result = await _fetch_page(client, resource_id, offset)
            page_records = result["records"]
            records.extend(page_records)

            total = result["total"]
            offset += len(page_records)
            if offset >= total or not page_records:
                break

    df = pd.DataFrame.from_records(records)
    df = df.drop(columns=["_id"], errors="ignore")
    df = df.replace(SENTINEL_VALUES, pd.NA)

    if "year" in df.columns:
        df["year"] = pd.to_numeric(df["year"], errors="coerce")
    for col in df.columns:
        if col in ("year", "industry", "occupation"):
            continue
        numeric = pd.to_numeric(df[col], errors="coerce")
        if numeric.notna().any():
            df[col] = numeric

    return df
