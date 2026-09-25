import pytest

from app.data.views import build_totals_view_sql, build_typed_view_sql, view_name_for

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


# --- rule-carrying views: total rows, overlapping values, default_slice ------------


def test_default_slice_keeps_only_the_listed_values():
    rules = {"default_slice": {"industry": ["manufacturing", "construction"]}}

    sql = build_typed_view_sql("retrenchment_by_industry", [(DATASET_A, PROFILE)], rules)

    assert "\"industry\" IN ('manufacturing', 'construction')" in sql


def test_exclude_values_removes_totals_and_overlaps():
    rules = {"exclude_values": {"sex": ["Total"], "hours_bucket": ["Total", "More Than 48 Hours"]}}

    sql = build_typed_view_sql("mom_usual_hours", [(DATASET_A, MOM_PROFILE)], rules)

    assert "\"sex\" NOT IN ('Total')" in sql
    assert "\"hours_bucket\" NOT IN ('Total', 'More Than 48 Hours')" in sql


def test_no_rules_means_no_where_clause():
    sql = build_typed_view_sql("retrenchment_by_industry", [(DATASET_A, PROFILE)])

    assert "AND" not in sql  # only the dataset_id filter, no rule predicates appended


def test_rule_values_are_escaped():
    rules = {"exclude_values": {"industry": ["o'brien"]}}

    sql = build_typed_view_sql("x", [(DATASET_A, PROFILE)], rules)

    assert "'o''brien'" in sql


def test_rule_column_must_exist_in_profile():
    rules = {"default_slice": {"not_a_column": ["x"]}}

    with pytest.raises(ValueError, match="not_a_column"):
        build_typed_view_sql("x", [(DATASET_A, PROFILE)], rules)


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
