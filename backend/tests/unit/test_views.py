from types import SimpleNamespace

import pytest

from app.data.views import build_totals_view_sql, build_typed_view_sql, plan_views, view_name_for

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


# --- exclude_values: total rows and overlapping buckets never reach the view --------


def test_exclude_values_filters_on_the_raw_record_not_the_select_alias():
    # Postgres can't see SELECT aliases in WHERE; filtering on "sex" would fail at CREATE VIEW
    exclude = {"sex": ["Total"], "hours_bucket": ["Total", "More Than 48 Hours"]}

    sql = build_typed_view_sql("mom_usual_hours", [(DATASET_A, MOM_PROFILE)], exclude)

    assert "(record->>'sex') NOT IN ('Total')" in sql
    assert "(record->>'hours_bucket') NOT IN ('Total', 'More Than 48 Hours')" in sql
    assert 'AND "sex"' not in sql


def test_exclude_values_keeps_rows_with_a_missing_value():
    sql = build_typed_view_sql("x", [(DATASET_A, MOM_PROFILE)], {"sex": ["Total"]})

    assert "(record->>'sex') IS NULL OR" in sql


def test_exclude_values_apply_to_every_group_member():
    sql = build_typed_view_sql(
        "mom_usual_hours", [(DATASET_A, MOM_PROFILE), (DATASET_B, MOM_PROFILE)], {"sex": ["Total"]}
    )

    assert sql.count("NOT IN ('Total')") == 2


def test_no_exclusions_means_only_the_dataset_filter():
    sql = build_typed_view_sql("retrenchment_by_industry", [(DATASET_A, PROFILE)])

    assert "AND" not in sql


def test_excluded_values_are_escaped():
    sql = build_typed_view_sql("x", [(DATASET_A, PROFILE)], {"industry": ["o'brien"]})

    assert "'o''brien'" in sql


def test_excluded_column_must_exist_in_profile():
    with pytest.raises(ValueError, match="not_a_column"):
        build_typed_view_sql("x", [(DATASET_A, PROFILE)], {"not_a_column": ["x"]})


# --- planning views from the manifest -----------------------------------------------


def _dataset(dataset_id, profile):
    return SimpleNamespace(id=dataset_id, schema_profile=profile)


def test_views_ignore_default_slice():
    # default_slice is a "when the query doesn't filter this column" rule for the pandas
    # path; baked into a view it would hide every non-Total MOM row permanently.
    manifest = [{"id": "mom_2024", "default_slice": {"sex": ["Total"]}}]

    plans = plan_views(manifest, {"mom_2024": _dataset(DATASET_A, MOM_PROFILE)})

    assert plans["mom_2024"].exclude_values == {}


def test_group_members_share_one_view_with_their_exclusions():
    exclude = {"sex": ["Total"]}
    manifest = [
        {"id": "mom_2023", "group": "mom", "exclude_values": exclude},
        {"id": "mom_2024", "group": "mom", "exclude_values": exclude},
    ]
    datasets = {
        "mom_2023": _dataset(DATASET_A, MOM_PROFILE),
        "mom_2024": _dataset(DATASET_B, MOM_PROFILE),
    }

    plans = plan_views(manifest, datasets)

    assert list(plans) == ["mom"]
    assert [m[0] for m in plans["mom"].members] == [DATASET_A, DATASET_B]
    assert plans["mom"].exclude_values == exclude


def test_group_members_must_declare_the_same_exclusions():
    manifest = [
        {"id": "mom_2023", "group": "mom", "exclude_values": {"sex": ["Total"]}},
        {"id": "mom_2024", "group": "mom"},
    ]
    datasets = {
        "mom_2023": _dataset(DATASET_A, MOM_PROFILE),
        "mom_2024": _dataset(DATASET_B, MOM_PROFILE),
    }

    with pytest.raises(ValueError, match="exclude_values"):
        plan_views(manifest, datasets)


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
