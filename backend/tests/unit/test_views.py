import pytest

from app.data.views import build_typed_view_sql, view_name_for

DATASET_A = "11111111-1111-1111-1111-111111111111"
DATASET_B = "22222222-2222-2222-2222-222222222222"

PROFILE = [
    {"column": "year", "role": "time"},
    {"column": "industry", "role": "dimension"},
    {"column": "retrench", "role": "measure"},
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
