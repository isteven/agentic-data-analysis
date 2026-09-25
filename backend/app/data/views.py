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

from app.data.structure import ancestor_chain
from app.models.dataset import Dataset

VIEW_SCHEMA = "data"
READER_ROLE = "data_reader"  # created by migration 0004
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


def _raw(column: str) -> str:
    # Filters use the raw JSON value: Postgres can't refer to SELECT aliases in WHERE
    return f"(record->>{_quote_literal(column)})"


def merge_structure(profiles: list[list[dict]]) -> dict[str, dict]:
    """One structure per dimension for a view whose members (e.g. one file per year) were
    profiled separately: union of exclusions, parents and unverified periods."""
    merged: dict[str, dict] = {}
    for profile in profiles:
        for c in profile:
            if c["role"] != "dimension" or not any(
                c.get(k) for k in ("parents", "exclude_values", "unverified_periods")
            ):
                continue
            m = merged.setdefault(
                c["column"], {"parents": {}, "exclude_values": set(), "unverified_periods": []}
            )
            for child, parent in (c.get("parents") or {}).items():
                m["parents"].setdefault(child, parent)
            m["exclude_values"].update(c.get("exclude_values") or [])
            for period in c.get("unverified_periods") or []:
                if period not in m["unverified_periods"]:
                    m["unverified_periods"].append(period)
    for m in merged.values():
        m["levels"] = max((len(ancestor_chain(v, m["parents"])) for v in m["parents"]), default=1)
    return merged


def _level_columns(column: str, structure: dict) -> list[str]:
    """`<column>_level_1` = top of the hierarchy, and so on down; a value with fewer
    ancestors repeats itself at the deeper levels, so GROUP BY any level covers every row
    exactly once."""
    parents, raw = structure["parents"], _raw(column)
    leaves = {v for v in parents if v not in set(parents.values())}
    out = []
    for level in range(1, structure["levels"]):
        whens = []
        for leaf in sorted(leaves):
            chain = ancestor_chain(leaf, parents)
            name = chain[min(level - 1, len(chain) - 1)]
            if name != leaf:
                whens.append(f"WHEN {_quote_literal(leaf)} THEN {_quote_literal(name)}")
        body = "\n        ".join(whens)
        out.append(
            f"CASE {raw}\n        {body}\n        ELSE {raw} END "
            f"AS {_quote_identifier(f'{column}_level_{level}')}"
        )
    return out


def _structure_clauses(structure: dict[str, dict], time_col: str | None) -> list[str]:
    """Keep only rows safe to add up: lowest-level values (parents are the sum of their
    children), no grand totals or overlapping buckets, no second classification scheme,
    and no years whose classification couldn't be verified."""
    clauses = []
    for column, s in structure.items():
        drop = sorted(set(s["exclude_values"]) | set(s["parents"].values()))
        if drop:
            raw = _raw(column)
            literals = ", ".join(_quote_literal(v) for v in drop)
            # rows with no value are kept - a bare NOT IN would silently drop them
            clauses.append(f"({raw} IS NULL OR {raw} NOT IN ({literals}))")
        if time_col:
            for lo, hi in s["unverified_periods"]:
                clauses.append(f"{_raw(time_col)}::numeric NOT BETWEEN {float(lo)} AND {float(hi)}")
    return clauses


def _member_select(dataset_id: str, profile: list[dict], structure: dict[str, dict]) -> str:
    dataset_id = str(uuid.UUID(dataset_id))  # raises ValueError if not a UUID
    columns = [
        f"(record->>{_quote_literal(c['column'])})::{_CASTS[c['role']]} "
        f"AS {_quote_identifier(c['column'])}"
        for c in profile
    ]
    for c in profile:
        if c["column"] in structure:
            columns += _level_columns(c["column"], structure[c["column"]])
    time_col = next((c["column"] for c in profile if c["role"] == "time"), None)
    where = "\n  AND ".join(
        [f"dataset_id = '{dataset_id}'", *_structure_clauses(structure, time_col)]
    )
    return "SELECT\n    " + ",\n    ".join(columns) + f"\nFROM dataset_records\nWHERE {where}"


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
    structure = merge_structure([p for _, p in ordered])
    body = "\nUNION ALL\n".join(_member_select(d, p, structure) for d, p in ordered)
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


def plan_views(
    manifest: list[dict], datasets_by_key: dict
) -> dict[str, list[tuple[str, list[dict]]]]:
    """View name -> its members (dataset id, profile). What a view keeps comes from the
    inferred structure in each profile, not from the manifest."""
    plans: dict[str, list[tuple[str, list[dict]]]] = {}
    for entry in manifest:
        dataset = datasets_by_key.get(entry["id"])
        if dataset is None or not dataset.schema_profile:
            continue
        plans.setdefault(view_name_for(entry), []).append((str(dataset.id), dataset.schema_profile))
    return plans


def _has_totals_view(profile: list[dict]) -> bool:
    # without an additive measure the "totals" view would only list the periods
    has_time = any(c["role"] == "time" for c in profile)
    return has_time and any(c["role"] == "measure" and c.get("additive") for c in profile)


def view_catalog(plans: dict[str, list[tuple[str, list[dict]]]]) -> dict[str, list[dict]]:
    """Every generated view and the columns it exposes (role, additivity, values) -
    what the SQL gate checks queries against and what the planner is shown."""
    catalog: dict[str, list[dict]] = {}
    for view_name, members in plans.items():
        profile = members[0][1]
        structure = merge_structure([p for _, p in members])
        columns = [dict(c) for c in profile]
        for column, s in structure.items():
            columns += [
                {"column": f"{column}_level_{level}", "role": "dimension", "level_of": column}
                for level in range(1, s["levels"])
            ]
        catalog[view_name] = columns
        if _has_totals_view(profile):
            catalog[f"{view_name}_totals"] = [
                dict(c)
                for c in profile
                if c["role"] == "time" or (c["role"] == "measure" and c.get("additive"))
            ]
    return catalog


async def load_view_catalog(session: AsyncSession, manifest: list[dict]) -> dict[str, list[dict]]:
    datasets = {d.dataset_key: d for d in (await session.scalars(select(Dataset))).all()}
    return view_catalog(plan_views(manifest, datasets))


async def rebuild_views(session: AsyncSession, manifest: list[dict]) -> list[str]:
    """Drop and recreate every view in the `data` schema from current profiles, plus one
    generated totals-per-time-period view per typed view. The schema holds only generated
    views, so dropping it loses nothing."""
    datasets = {d.dataset_key: d for d in (await session.scalars(select(Dataset))).all()}
    plans = plan_views(manifest, datasets)

    await session.execute(text(f"DROP SCHEMA IF EXISTS {VIEW_SCHEMA} CASCADE"))
    await session.execute(text(f"CREATE SCHEMA {VIEW_SCHEMA}"))
    for view_name, members in plans.items():
        await session.execute(text(build_typed_view_sql(view_name, members)))
        profile = members[0][1]
        if _has_totals_view(profile):
            totals_view = f"{view_name}_totals"
            await session.execute(text(build_totals_view_sql(totals_view, view_name, profile)))
    # dropping the schema dropped the grants too; planner SQL runs as this role
    await session.execute(text(f"GRANT USAGE ON SCHEMA {VIEW_SCHEMA} TO {READER_ROLE}"))
    await session.execute(
        text(f"GRANT SELECT ON ALL TABLES IN SCHEMA {VIEW_SCHEMA} TO {READER_ROLE}")
    )
    return sorted(plans)
