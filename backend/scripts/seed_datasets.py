import asyncio
import hashlib
import sys
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.data.cleaning import clean_dataset
from app.data.manifest import DATA_ROOT, load_manifest
from app.data.parsers.csv_parser import read_csv
from app.data.parsers.excel_parser import read_mom_hours_sheet
from app.data.profiler import profile_dataframe
from app.db.session import AsyncSessionLocal
from app.models.dataset import Dataset


def content_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_dataframe(entry: dict):
    path = DATA_ROOT / entry["file_path"]

    if entry["format"] == "csv":
        df = read_csv(str(path))
    elif entry["format"] == "xlsx":
        df = read_mom_hours_sheet(str(path), entry["sheet_name"])
    else:
        raise NotImplementedError(f"Format '{entry['format']}' not yet handled (dataset: {entry['id']})")

    before = len(df)
    df = clean_dataset(df, entry)
    if len(df) != before:
        print(f"  cleaning rules applied (manifest): {before} -> {len(df)} rows")

    return df


def _has_seedable_file(entry: dict) -> bool:
    """True for file-mode datasets, and for api-mode datasets with a file fallback -
    both cases are seeded from the same local file via build_dataframe()."""
    mode = entry.get("mode")
    return mode == "file" or (mode == "api" and entry.get("api_fallback") == "file")


async def seed_dataset(session, entry: dict) -> None:
    if not _has_seedable_file(entry):
        print(f"skip {entry['id']}: mode={entry.get('mode')}, no file fallback configured")
        return

    path = DATA_ROOT / entry["file_path"]
    if not path.exists():
        print(f"skip {entry['id']}: source file not found at {path}")
        return

    hash_ = content_hash(path)

    existing = await session.scalar(
        select(Dataset).where(Dataset.dataset_key == entry["id"])
    )
    # also re-seed rows created before profiling existed, so every dataset gets a profile
    if existing is not None and existing.content_hash == hash_ and existing.schema_profile:
        print(f"skip {entry['id']}: already seeded, content unchanged")
        return

    try:
        df = build_dataframe(entry)
    except NotImplementedError as exc:
        print(f"skip {entry['id']}: {exc}")
        return

    quality_report = {
        "row_count": int(len(df)),
        "column_count": int(len(df.columns)),
        "null_counts": {col: int(df[col].isna().sum()) for col in df.columns},
    }
    schema_profile = profile_dataframe(df, entry)

    if existing is None:
        existing = Dataset(
            dataset_key=entry["id"],
            source=entry["source"],
            title=entry["title"],
            format=entry["format"],
            mode=entry["mode"],
            resource_id=entry.get("resource_id"),
            raw_cache_path=str(path),
            content_hash=hash_,
            quality_report=quality_report,
            schema_profile=schema_profile,
        )
        session.add(existing)
    else:
        existing.content_hash = hash_
        existing.quality_report = quality_report
        existing.schema_profile = schema_profile
        existing.raw_cache_path = str(path)

    await session.commit()
    print(f"seeded {entry['id']}: {quality_report['row_count']} rows, {quality_report['column_count']} columns")


async def main() -> None:
    manifest = load_manifest()
    async with AsyncSessionLocal() as session:
        for entry in manifest:
            await seed_dataset(session, entry)


if __name__ == "__main__":
    asyncio.run(main())
