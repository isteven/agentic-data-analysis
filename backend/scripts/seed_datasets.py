import asyncio
import hashlib
import json
import logging
import sys
from pathlib import Path

from sqlalchemy import delete, exists, insert, select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.data.cleaning import clean_dataset
from app.data.manifest import DATA_ROOT, load_manifest
from app.data.parsers.csv_parser import read_csv
from app.data.parsers.excel_parser import read_mom_hours_sheet
from app.data.profiler import PROFILER_VERSION, profile_dataframe
from app.data.records import to_records
from app.data.views import rebuild_views
from app.db.session import AsyncSessionLocal
from app.models.analysis_run import AnalysisRunDataset
from app.models.dataset import Dataset
from app.models.dataset_record import DatasetRecord
from app.models.finding import Finding

logger = logging.getLogger(__name__)


def manifest_entry_hash(entry: dict) -> str:
    return hashlib.sha256(json.dumps(entry, sort_keys=True, default=str).encode()).hexdigest()


def content_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_dataframe(entry: dict):
    path = DATA_ROOT / entry["file_path"]

    if entry["format"] == "csv":
        df = read_csv(str(path))
    elif entry["format"] == "xlsx":
        df = read_mom_hours_sheet(str(path), entry["sheet_name"])
    else:
        raise NotImplementedError(
            f"Format '{entry['format']}' not yet handled (dataset: {entry['id']})"
        )

    before = len(df)
    df = clean_dataset(df, entry)
    if len(df) != before:
        logger.info("cleaning rules applied (manifest): %s -> %s rows", before, len(df))

    return df


def _has_seedable_file(entry: dict) -> bool:
    """True for file-mode datasets, and for api-mode datasets with a file fallback -
    both cases are seeded from the same local file via build_dataframe()."""
    mode = entry.get("mode")
    return mode == "file" or (mode == "api" and entry.get("api_fallback") == "file")


async def seed_dataset(session, entry: dict) -> None:
    if not _has_seedable_file(entry):
        logger.info("skip %s: mode=%s, no file fallback configured", entry["id"], entry.get("mode"))
        return

    path = DATA_ROOT / entry["file_path"]
    if not path.exists():
        logger.warning("skip %s: source file not found at %s", entry["id"], path)
        return

    hash_ = content_hash(path)
    # column_meta (units, descriptions) is baked into the profile, so a manifest-only
    # edit must also re-seed - otherwise it is silently ignored until the data changes.
    entry_hash = manifest_entry_hash(entry)

    existing = await session.scalar(select(Dataset).where(Dataset.dataset_key == entry["id"]))
    # also re-seed datasets seeded before stored rows existed, or by an older profiler
    if (
        existing is not None
        and existing.content_hash == hash_
        and (existing.quality_report or {}).get("profiler_version") == PROFILER_VERSION
        and (existing.quality_report or {}).get("manifest_hash") == entry_hash
        and await _has_records(session, existing.id)
    ):
        logger.info("skip %s: already seeded, content unchanged", entry["id"])
        return

    try:
        df = build_dataframe(entry)
    except NotImplementedError as exc:
        logger.warning("skip %s: %s", entry["id"], exc)
        return

    quality_report = {
        "row_count": len(df),
        "column_count": len(df.columns),
        "null_counts": {col: int(df[col].isna().sum()) for col in df.columns},
        "profiler_version": PROFILER_VERSION,
        "manifest_hash": entry_hash,
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

    await session.flush()  # assigns existing.id for a new dataset
    await _replace_records(session, existing.id, df)
    await session.commit()
    logger.info(
        "seeded %s: %s rows, %s columns",
        entry["id"],
        quality_report["row_count"],
        quality_report["column_count"],
    )


async def _has_records(session, dataset_id) -> bool:
    return bool(
        await session.scalar(select(exists().where(DatasetRecord.dataset_id == dataset_id)))
    )


async def _replace_records(session, dataset_id, df) -> None:
    await session.execute(delete(DatasetRecord).where(DatasetRecord.dataset_id == dataset_id))
    rows = [
        {"dataset_id": dataset_id, "row_num": i, "record": record}
        for i, record in enumerate(to_records(df))
    ]
    if rows:
        await session.execute(insert(DatasetRecord), rows)


async def prune_removed_datasets(session, manifest: list[dict]) -> None:
    """Datasets dropped from the manifest lose their stored rows. Their catalog row is
    deleted too unless a past analysis cites it - then it stays, so that history still
    resolves. Nothing on the query path reads catalog rows outside the manifest."""
    keep = {entry["id"] for entry in manifest}
    removed = (await session.scalars(select(Dataset).where(Dataset.dataset_key.not_in(keep)))).all()
    for dataset in removed:
        await session.execute(delete(DatasetRecord).where(DatasetRecord.dataset_id == dataset.id))
        cited = await session.scalar(
            select(
                exists().where(AnalysisRunDataset.dataset_id == dataset.id)
                | exists().where(Finding.dataset_id == dataset.id)
            )
        )
        if cited:
            logger.info("pruned rows of %s: not in manifest, kept for past runs", dataset.dataset_key)
        else:
            await session.delete(dataset)
            logger.info("pruned %s: not in manifest", dataset.dataset_key)
    await session.commit()


async def main() -> None:
    manifest = load_manifest()
    async with AsyncSessionLocal() as session:
        await prune_removed_datasets(session, manifest)
        for entry in manifest:
            await seed_dataset(session, entry)
        # Views are derived, so rebuilding them every run keeps them in step with the
        # manifest and profiles even when no dataset changed.
        views = await rebuild_views(session, manifest)
        await session.commit()
        logger.info("views rebuilt in schema data: %s", ", ".join(views))


if __name__ == "__main__":
    configure_logging(get_settings().log_level)
    asyncio.run(main())
