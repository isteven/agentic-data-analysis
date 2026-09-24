"""Typed views over `dataset_records`, generated from each dataset's schema profile.

Rows are stored generically (one JSONB document per source row) so there's one fixed,
Alembic-managed table; the per-dataset objects are views in the `data` schema, which are
derived and can be rebuilt at any time without data loss (ARCHITECTURE.md §3.2). Planned
SQL generation queries these views, never the JSON directly.
"""

import re
import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dataset import Dataset

VIEW_SCHEMA = "data"
_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")

# numeric::integer tolerates years stored as 2020.0 as well as 2020
_CASTS = {"time": "numeric::integer", "measure": "double precision", "dimension": "text"}


def view_name_for(entry: dict) -> str:
    """Datasets sharing a manifest `group` (e.g. one file per year) form one view."""
    name = entry.get("group") or entry["id"]
    if not _IDENTIFIER.match(name):
        raise ValueError(f"'{name}' is not a safe view name (lowercase letters, digits, _)")
    return name


def _quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _member_select(dataset_id: str, profile: list[dict]) -> str:
    dataset_id = str(uuid.UUID(dataset_id))  # raises ValueError if not a UUID
    columns = ",\n    ".join(
        f"(record->>{_quote_literal(c['column'])})::{_CASTS[c['role']]} "
        f"AS {_quote_identifier(c['column'])}"
        for c in profile
    )
    return f"SELECT\n    {columns}\nFROM dataset_records\nWHERE dataset_id = '{dataset_id}'"


def build_typed_view_sql(view_name: str, members: list[tuple[str, list[dict]]]) -> str:
    if not _IDENTIFIER.match(view_name):
        raise ValueError(f"'{view_name}' is not a safe view name")
    first_columns = [c["column"] for c in members[0][1]]
    for dataset_id, profile in members[1:]:
        if sorted(c["column"] for c in profile) != sorted(first_columns):
            raise ValueError(
                f"Datasets in view '{view_name}' must have the same columns; "
                f"{dataset_id} differs from {members[0][0]}"
            )
    # Same column order in every member, so UNION ALL lines up.
    ordered = [
        (dataset_id, sorted(profile, key=lambda c: first_columns.index(c["column"])))
        for dataset_id, profile in members
    ]
    body = "\nUNION ALL\n".join(_member_select(d, p) for d, p in ordered)
    return f"CREATE VIEW {VIEW_SCHEMA}.{view_name} AS\n{body}"


async def rebuild_views(session: AsyncSession, manifest: list[dict]) -> list[str]:
    """Drop and recreate every view in the `data` schema from current profiles. The schema
    holds only generated views, so dropping it loses nothing."""
    datasets = {d.dataset_key: d for d in (await session.scalars(select(Dataset))).all()}
    members: dict[str, list[tuple[str, list[dict]]]] = {}
    for entry in manifest:
        dataset = datasets.get(entry["id"])
        if dataset is None or not dataset.schema_profile:
            continue
        members.setdefault(view_name_for(entry), []).append(
            (str(dataset.id), dataset.schema_profile)
        )

    await session.execute(text(f"DROP SCHEMA IF EXISTS {VIEW_SCHEMA} CASCADE"))
    await session.execute(text(f"CREATE SCHEMA {VIEW_SCHEMA}"))
    for view_name, view_members in members.items():
        await session.execute(text(build_typed_view_sql(view_name, view_members)))
    return sorted(members)
