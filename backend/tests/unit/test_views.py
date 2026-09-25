from types import SimpleNamespace

import pytest

from app.data.views import (
    build_totals_view_sql,
    build_typed_view_sql,
    merge_structure,
    plan_views,
    view_catalog,
    view_name_for,
)

DATASET_A = "11111111-1111-1111-1111-111111111111"
DATASET_B = "22222222-2222-2222-2222-222222222222"

PROFILE = [
    {"column": "year", "role": "time"},
    {"column": "industry", "role": "dimension"},
    {"column": "retrench", "role": "measure", "additive": True},
]

MOM_PROFILE = [
    {"column": "year", "role": "time"},
    {"column": "sex", "role": "dimension"},
    {"column": "hours_bucket", "role": "dimension"},
    {"column": "value", "role": "measure", "additive": True},
]


def test_view_name_defaults_to_dataset_id():
    assert view_name_for({"id": "retrenchment_by_industry"}) == "retrenchment_by_industry"


def test_view_name_uses_group_when_declared():
    entry = {"id": "mom_hours_2024", "group": "mom_usual_hours"}

    assert view_name_for(entry) == "mom_usual_hours"


def test_view_name_rejects_unsafe_identifier():
    with pytest.raises(ValueError):
        view_name_for({"id": "bad name; drop table x"})


def test_columns_are_typed_by_role():
    sql = build_typed_view_sql("retrenchment_by_industry", [(DATASET_A, PROFILE)])

    assert "CREATE VIEW data.retrenchment_by_industry AS" in sql
    assert "(record->>'year')::numeric::integer AS \"year\"" in sql
    assert "(record->>'industry')::text AS \"industry\"" in sql
    assert "(record->>'retrench')::double precision AS \"retrench\"" in sql
    assert f"WHERE dataset_id = '{DATASET_A}'" in sql


def test_group_members_are_combined_with_union_all():
    sql = build_typed_view_sql("mom_usual_hours", [(DATASET_A, PROFILE), (DATASET_B, PROFILE)])

    assert sql.count("UNION ALL") == 1
    assert f"'{DATASET_A}'" in sql and f"'{DATASET_B}'" in sql


def test_group_members_must_share_columns():
    other = [{"column": "year", "role": "time"}, {"column": "value", "role": "measure"}]

    with pytest.raises(ValueError, match="columns"):
        build_typed_view_sql("mom_usual_hours", [(DATASET_A, PROFILE), (DATASET_B, other)])


def test_column_names_from_data_are_escaped():
    profile = [{"column": 'it\'s "odd"', "role": "dimension"}]

    sql = build_typed_view_sql("x", [(DATASET_A, profile)])

    assert '(record->>\'it\'\'s "odd"\')::text AS "it\'s ""odd"""' in sql


def test_dataset_id_must_be_a_uuid():
    with pytest.raises(ValueError):
        build_typed_view_sql("x", [("not-a-uuid'; drop", PROFILE)])


# --- structure-driven filtering: only rows safe to add up reach the view ------------

MOM_WITH_TOTALS = [
    {"column": "year", "role": "time"},
    {
        "column": "sex",
        "role": "dimension",
        "parents": {},
        "exclude_values": ["Total"],
        "unverified_periods": [],
    },
    {
        "column": "hours_bucket",
        "role": "dimension",
        "parents": {},
        "exclude_values": ["Total", "More Than 48 Hours"],
        "unverified_periods": [],
    },
    {"column": "value", "role": "measure", "additive": True},
]

INDUSTRY_TREE = {
    "wholesale trade": "wholesale and retail trade",
    "retail trade": "wholesale and retail trade",
    "wholesale and retail trade": "services",
    "it services": "services",
}
HIERARCHY_PROFILE = [
    {"column": "year", "role": "time"},
    {
        "column": "industry",
        "role": "dimension",
        "parents": INDUSTRY_TREE,
        "exclude_values": [],
        "unverified_periods": [[1998, 2005]],
        "levels": 3,
    },
    {"column": "retrench", "role": "measure", "additive": True},
]


def test_excluded_values_filter_on_the_raw_record_not_the_select_alias():
    # Postgres can't see SELECT aliases in WHERE; filtering on "sex" would fail at CREATE VIEW
    sql = build_typed_view_sql("mom", [(DATASET_A, MOM_WITH_TOTALS)])

    assert "(record->>'sex') NOT IN ('Total')" in sql
    assert "(record->>'hours_bucket') NOT IN ('More Than 48 Hours', 'Total')" in sql
    assert 'AND "sex"' not in sql


def test_excluding_keeps_rows_with_a_missing_value():
    sql = build_typed_view_sql("mom", [(DATASET_A, MOM_WITH_TOTALS)])

    assert "(record->>'sex') IS NULL OR" in sql


def test_parents_are_dropped_so_only_lowest_level_rows_remain():
    sql = build_typed_view_sql("r", [(DATASET_A, HIERARCHY_PROFILE)])

    assert "NOT IN ('services', 'wholesale and retail trade')" in sql


def test_level_columns_map_each_leaf_to_its_ancestors():
    sql = build_typed_view_sql("r", [(DATASET_A, HIERARCHY_PROFILE)])

    assert "WHEN 'wholesale trade' THEN 'services'" in sql  # level 1 = top
    assert "WHEN 'wholesale trade' THEN 'wholesale and retail trade'" in sql  # level 2
    assert '"industry_level_1"' in sql and '"industry_level_2"' in sql
    # a leaf one level below the top repeats itself at level 2 - no CASE branch needed
    assert "WHEN 'it services' THEN 'it services'" not in sql


def test_unverified_periods_are_left_out():
    sql = build_typed_view_sql("r", [(DATASET_A, HIERARCHY_PROFILE)])

    assert "(record->>'year')::numeric NOT BETWEEN 1998.0 AND 2005.0" in sql


def test_no_structure_means_only_the_dataset_filter():
    sql = build_typed_view_sql("retrenchment_by_industry", [(DATASET_A, PROFILE)])

    assert "AND" not in sql


def test_excluded_values_are_escaped():
    profile = [
        {
            "column": "industry",
            "role": "dimension",
            "parents": {},
            "exclude_values": ["o'brien"],
            "unverified_periods": [],
        },
    ]

    sql = build_typed_view_sql("x", [(DATASET_A, profile)])

    assert "'o''brien'" in sql


def test_group_members_structures_are_merged():
    # one year's file may prove a relation another year's doesn't; the view needs both
    a = [dict(c) for c in MOM_WITH_TOTALS]
    b = [dict(c) for c in MOM_WITH_TOTALS]
    b[1] = {**b[1], "exclude_values": ["Total", "Unknown"]}

    merged = merge_structure([a, b])

    assert merged["sex"]["exclude_values"] == {"Total", "Unknown"}
    sql = build_typed_view_sql("mom", [(DATASET_A, a), (DATASET_B, b)])
    assert sql.count("NOT IN ('Total', 'Unknown')") == 2


# --- planning views from the manifest -----------------------------------------------


def _dataset(dataset_id, profile):
    return SimpleNamespace(id=dataset_id, schema_profile=profile)


def test_group_members_share_one_view():
    manifest = [{"id": "mom_2023", "group": "mom"}, {"id": "mom_2024", "group": "mom"}]
    datasets = {
        "mom_2023": _dataset(DATASET_A, MOM_PROFILE),
        "mom_2024": _dataset(DATASET_B, MOM_PROFILE),
    }

    plans = plan_views(manifest, datasets)

    assert list(plans) == ["mom"]
    assert [m[0] for m in plans["mom"]] == [DATASET_A, DATASET_B]


def test_manifest_rules_no_longer_shape_views():
    # data rules come from the inferred structure, not per-dataset manifest entries
    manifest = [
        {
            "id": "mom_2024",
            "default_slice": {"sex": ["Total"]},
            "exclude_values": {"sex": ["Total"]},
        }
    ]

    plans = plan_views(manifest, {"mom_2024": _dataset(DATASET_A, MOM_PROFILE)})

    assert "NOT IN" not in build_typed_view_sql("mom_2024", plans["mom_2024"])


def test_unseeded_or_unprofiled_datasets_get_no_view():
    manifest = [{"id": "a"}, {"id": "b"}]

    plans = plan_views(manifest, {"b": _dataset(DATASET_B, None)})

    assert plans == {}


# --- generated totals-per-time-period view -----------------------------------------


def test_totals_view_sums_every_additive_measure_grouped_by_time():
    sql = build_totals_view_sql(
        "retrenchment_by_industry_totals", "retrenchment_by_industry", PROFILE
    )

    assert 'SUM("retrench") AS "retrench"' in sql
    assert 'GROUP BY "year"' in sql
    assert '"industry"' not in sql  # dimensions are dropped, not grouped by


def test_totals_view_omits_non_additive_measures():
    profile = PROFILE + [{"column": "rate", "role": "measure", "additive": False}]

    sql = build_totals_view_sql("t", "retrenchment_by_industry", profile)

    assert '"rate"' not in sql


def test_totals_view_requires_a_time_column():
    profile = [
        {"column": "industry", "role": "dimension"},
        {"column": "retrench", "role": "measure", "additive": True},
    ]

    with pytest.raises(ValueError, match="time"):
        build_totals_view_sql("t", "retrenchment_by_industry", profile)


def test_catalog_describes_every_member_file_not_just_the_first():
    def mom_file(year, sexes):
        return [
            {"column": "year", "role": "time", "min": year, "max": year},
            {
                "column": "sex",
                "role": "dimension",
                "values": sexes,
                "distinct": len(sexes),
                "exclude_values": ["Total"],
            },
            {"column": "value", "role": "measure", "additive": True, "min": 0.1, "max": 9.0},
        ]

    catalog = view_catalog(
        {"mom": [(DATASET_A, mom_file(2023, ["Female", "Total"])), (DATASET_B, mom_file(2025, ["Male", "Total"]))]}
    )
    year, sex, _ = catalog["mom"]

    assert (year["min"], year["max"]) == (2023, 2025)
    assert sex["values"] == ["Female", "Male"]  # union, minus the excluded grand total
    assert sex["distinct"] == 2
