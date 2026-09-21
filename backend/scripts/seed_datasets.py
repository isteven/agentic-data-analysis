import asyncio
import hashlib
import sys
from pathlib import Path

import yaml
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.data.parsers.csv_parser import read_csv  # noqa: E402
from app.data.parsers.excel_parser import read_mom_hours_sheet  # noqa: E402
from app.db.session import AsyncSessionLocal  # noqa: E402
from app.models.dataset import Dataset  # noqa: E402

DATA_ROOT = Path(__file__).resolve().parent.parent / "data"
MANIFEST_PATH = DATA_ROOT / "manifest.yaml"

# Industry x occupation classification changed pre-2006 (84-129 rows/year vs. 126 after);
# only the stabilized years are loaded.
RETRENCHMENT_MIN_YEAR = 2006


def content_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_manifest() -> list[dict]:
    with open(MANIFEST_PATH) as f:
        manifest = yaml.safe_load(f)
    return manifest["datasets"]


def build_dataframe(entry: dict):
    path = DATA_ROOT / entry["file_path"]

    if entry["format"] == "csv":
        df = read_csv(str(path))
    elif entry["format"] == "xlsx":
        df = read_mom_hours_sheet(str(path), entry["sheet_name"])
    else:
        raise NotImplementedError(f"Format '{entry['format']}' not yet handled (dataset: {entry['id']})")

    if entry["id"] == "retrenchment_by_industry":
        before = len(df)
        df = df[df["year"] >= RETRENCHMENT_MIN_YEAR].reset_index(drop=True)
        print(
            f"  filtered to stabilized-classification years (>= {RETRENCHMENT_MIN_YEAR}): "
            f"{before} -> {len(df)} rows"
        )

    return df


async def seed_dataset(session, entry: dict) -> None:
    if entry.get("mode") != "file":
        print(f"skip {entry['id']}: mode={entry.get('mode')} (not a file-mode dataset)")
        return

    path = DATA_ROOT / entry["file_path"]
    if not path.exists():
        print(f"skip {entry['id']}: source file not found at {path}")
        return

    hash_ = content_hash(path)

    existing = await session.scalar(
        select(Dataset).where(Dataset.dataset_key == entry["id"])
    )
    if existing is not None and existing.content_hash == hash_:
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
        )
        session.add(existing)
    else:
        existing.content_hash = hash_
        existing.quality_report = quality_report
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
