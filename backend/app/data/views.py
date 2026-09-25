"""Typed views over `dataset_records`, generated from each dataset's schema profile.

Rows are stored generically (one JSONB document per source row) so there's one fixed,
Alembic-managed table; the per-dataset objects are views in the `data` schema, which are
derived and can be rebuilt at any time without data loss (ARCHITECTURE.md §3.2). Planned
SQL generation queries these views, never the JSON directly.
"""

import re
import uuid
from dataclasses import dataclass, field

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


def _exclusion_clauses(profile: list[dict], exclude_values: dict | None) -> list[str]:
    """Drop total rows and overlapping buckets (manifest `exclude_values`) so every row
    left in the view is safe to add up. Filters the raw JSON value: Postgres can't refer
    to SELECT aliases in WHERE. Rows with no value in that column are kept - a bare
    NOT IN would silently drop them."""
    columns = {c["column"] for c in profile}
    clauses = []
    for column, values in (exclude_values or {}).items():
        if column not in columns:
            raise ValueError(f"exclude_values column '{column}' is not in this dataset's profile")
        raw = f"(record->>{_quote_literal(column)})"
        literals = ", ".join(_quote_literal(v) for v in values)
        clauses.append(f"({raw} IS NULL OR {raw} NOT IN ({literals}))")
    return clauses


def _member_select(dataset_id: str, profile: list[dict], exclude_values: dict | None) -> str:
    dataset_id = str(uuid.UUID(dataset_id))  # raises ValueError if not a UUID
    columns = ",\n    ".join(
        f"(record->>{_quote_literal(c['column'])})::{_CASTS[c['role']]} "
        f"AS {_quote_identifier(c['column'])}"
        for c in profile
    )
    where = "\n  AND ".join(
        [f"dataset_id = '{dataset_id}'", *_exclusion_clauses(profile, exclude_values)]
    )
    return f"SELECT\n    {columns}\nFROM dataset_records\nWHERE {where}"


def build_typed_view_sql(
    view_name: str, members: list[tuple[str, list[dict]]], exclude_values: dict | None = None
) -> str:
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
    body = "\nUNION ALL\n".join(_member_select(d, p, exclude_values) for d, p in ordered)
    return f"CREATE VIEW {VIEW_SCHEMA}.{view_name} AS\n{body}"


def build_totals_view_sql(view_name: str, base_view_name: str, profile: list[dict]) -> str:
    """A generated 'totals per time period' view: SUM of every additive measure, grouped
    by the time column, over the (already rule-filtered) typed view. Dimensions are
    dropped rather than grouped by, since mixing them back in is exactly the
    double-counting this view exists to avoid (ARCHITECTURE.md §3.2)."""
    if not _IDENTIFIER.match(view_name):
        raise ValueError(f"'{view_name}' is not a safe view name")
    time_columns = [c["column"] for c in profile if c["role"] == "time"]
    if not time_columns:
        raise ValueError(f"'{base_view_name}' has no time column; can't build a totals view")
    time_column = time_columns[0]
    measures = [c["column"] for c in profile if c["role"] == "measure" and c.get("additive")]
    select_list = ",\n    ".join(
        [_quote_identifier(time_column)]
        + [f"SUM({_quote_identifier(m)}) AS {_quote_identifier(m)}" for m in measures]
    )
    return (
        f"CREATE VIEW {VIEW_SCHEMA}.{view_name} AS\n"
        f"SELECT\n    {select_list}\n"
        f"FROM {VIEW_SCHEMA}.{_quote_identifier(base_view_name)}\n"
        f"GROUP BY {_quote_identifier(time_column)}"
    )


@dataclass
class ViewPlan:
    members: list[tuple[str, list[dict]]] = field(default_factory=list)
    exclude_values: dict = field(default_factory=dict)


def plan_views(manifest: list[dict], datasets_by_key: dict) -> dict[str, ViewPlan]:
    """Which views to build, from the manifest and the seeded datasets. Only
    `exclude_values` shapes a view; `default_slice` is deliberately ignored - it means
    "when the query doesn't filter this column", which a fixed view can't express."""
    plans: dict[str, ViewPlan] = {}
    for entry in manifest:
        dataset = datasets_by_key.get(entry["id"])
        if dataset is None or not dataset.schema_profile:
            continue
        view_name = view_name_for(entry)
        exclude_values = entry.get("exclude_values") or {}
        plan = plans.get(view_name)
        if plan is None:
            plan = plans[view_name] = ViewPlan(exclude_values=exclude_values)
        elif plan.exclude_values != exclude_values:
            # One view, one set of rules: members declaring different ones is a manifest bug
            raise ValueError(
                f"Datasets in view '{view_name}' declare different exclude_values; "
                f"'{entry['id']}' differs from the first member"
            )
        plan.members.append((str(dataset.id), dataset.schema_profile))
    return plans


async def rebuild_views(session: AsyncSession, manifest: list[dict]) -> list[str]:
    """Drop and recreate every view in the `data` schema from current profiles, plus one
    generated totals-per-time-period view per typed view. The schema holds only generated
    views, so dropping it loses nothing."""
    datasets = {d.dataset_key: d for d in (await session.scalars(select(Dataset))).all()}
    plans = plan_views(manifest, datasets)

    await session.execute(text(f"DROP SCHEMA IF EXISTS {VIEW_SCHEMA} CASCADE"))
    await session.execute(text(f"CREATE SCHEMA {VIEW_SCHEMA}"))
    for view_name, plan in plans.items():
        await session.execute(
            text(build_typed_view_sql(view_name, plan.members, plan.exclude_values))
        )
        profile = plan.members[0][1]
        if any(c["role"] == "time" for c in profile):
            totals_view = f"{view_name}_totals"
            await session.execute(text(build_totals_view_sql(totals_view, view_name, profile)))
    return sorted(plans)
