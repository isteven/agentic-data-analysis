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


def _rule_where_clauses(profile: list[dict], rules: dict | None) -> list[str]:
    """`default_slice` (keep-only) and `exclude_values` (drop) manifest rules, turned into
    SQL predicates on the raw JSONB text value (applied before the role cast, so it works
    the same regardless of column type). Every rule column must exist in the profile -
    this is a manifest/profile mismatch, not a bad query, so it fails loudly."""
    if not rules:
        return []
    columns = {c["column"] for c in profile}
    clauses = []
    for column, values in (rules.get("default_slice") or {}).items():
        if column not in columns:
            raise ValueError(f"default_slice column '{column}' is not in this dataset's profile")
        literals = ", ".join(_quote_literal(v) for v in values)
        clauses.append(f"{_quote_identifier(column)} IN ({literals})")
    for column, values in (rules.get("exclude_values") or {}).items():
        if column not in columns:
            raise ValueError(f"exclude_values column '{column}' is not in this dataset's profile")
        literals = ", ".join(_quote_literal(v) for v in values)
        clauses.append(f"{_quote_identifier(column)} NOT IN ({literals})")
    return clauses


def _member_select(dataset_id: str, profile: list[dict], rules: dict | None) -> str:
    dataset_id = str(uuid.UUID(dataset_id))  # raises ValueError if not a UUID
    columns = ",\n    ".join(
        f"(record->>{_quote_literal(c['column'])})::{_CASTS[c['role']]} "
        f"AS {_quote_identifier(c['column'])}"
        for c in profile
    )
    where = " AND ".join([f"dataset_id = '{dataset_id}'", *_rule_where_clauses(profile, rules)])
    return f"SELECT\n    {columns}\nFROM dataset_records\nWHERE {where}"


def build_typed_view_sql(
    view_name: str, members: list[tuple[str, list[dict]]], rules: dict | None = None
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
    body = "\nUNION ALL\n".join(_member_select(d, p, rules) for d, p in ordered)
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


def _rules_for(entry: dict) -> dict:
    return {
        k: v
        for k, v in {
            "default_slice": entry.get("default_slice"),
            "exclude_values": entry.get("exclude_values"),
        }.items()
        if v
    }


async def rebuild_views(session: AsyncSession, manifest: list[dict]) -> list[str]:
    """Drop and recreate every view in the `data` schema from current profiles, plus one
    generated totals-per-time-period view per typed view. The schema holds only generated
    views, so dropping it loses nothing."""
    datasets = {d.dataset_key: d for d in (await session.scalars(select(Dataset))).all()}
    members: dict[str, list[tuple[str, list[dict]]]] = {}
    rules_by_view: dict[str, dict] = {}
    for entry in manifest:
        dataset = datasets.get(entry["id"])
        if dataset is None or not dataset.schema_profile:
            continue
        view_name = view_name_for(entry)
        members.setdefault(view_name, []).append((str(dataset.id), dataset.schema_profile))
        # Grouped datasets (e.g. one MOM file per year) share one view and must declare
        # the same rules, since the rules apply to the combined view, not a single member.
        entry_rules = _rules_for(entry)
        if entry_rules:
            rules_by_view.setdefault(view_name, entry_rules)

    await session.execute(text(f"DROP SCHEMA IF EXISTS {VIEW_SCHEMA} CASCADE"))
    await session.execute(text(f"CREATE SCHEMA {VIEW_SCHEMA}"))
    for view_name, view_members in members.items():
        rules = rules_by_view.get(view_name)
        await session.execute(text(build_typed_view_sql(view_name, view_members, rules)))
        profile = view_members[0][1]
        if any(c["role"] == "time" for c in profile):
            totals_view = f"{view_name}_totals"
            await session.execute(text(build_totals_view_sql(totals_view, view_name, profile)))
    return sorted(members)
