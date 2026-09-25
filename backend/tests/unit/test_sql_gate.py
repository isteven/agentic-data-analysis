import pytest

from app.data.sql_gate import SqlRejected, check_sql

CATALOG = {
    "retrenchment": [
        {"column": "year", "role": "time"},
        {"column": "industry", "role": "dimension"},
        {"column": "industry_level_1", "role": "dimension", "level_of": "industry"},
        {"column": "retrench", "role": "measure", "additive": True},
        {"column": "incidence", "role": "measure", "additive": False},
    ],
    "retrenchment_totals": [
        {"column": "year", "role": "time"},
        {"column": "retrench", "role": "measure", "additive": True},
    ],
}


def _rejected(sql: str) -> str:
    with pytest.raises(SqlRejected) as info:
        check_sql(sql, CATALOG)
    return str(info.value)


# --- allowed -----------------------------------------------------------------------


def test_aggregate_over_a_view_passes_and_is_regenerated():
    sql = check_sql(
        "select industry_level_1, sum(retrench) as total from data.retrenchment "
        "where year between 2020 and 2024 group by industry_level_1 order by total desc",
        CATALOG,
    )

    assert "SUM(retrench)" in sql and "data.retrenchment" in sql


def test_ctes_joins_and_window_functions_pass():
    check_sql(
        "WITH t AS (SELECT year, SUM(retrench) AS total FROM data.retrenchment GROUP BY year) "
        "SELECT t.year, t.total, t.total - LAG(t.total) OVER (ORDER BY t.year) AS change, "
        "r.retrench FROM t JOIN data.retrenchment_totals r ON r.year = t.year",
        CATALOG,
    )


def test_non_additive_measures_can_be_averaged():
    check_sql("SELECT year, AVG(incidence) FROM data.retrenchment GROUP BY year", CATALOG)


# --- refused -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM data.retrenchment",
        "UPDATE data.retrenchment SET retrench = 0",
        "INSERT INTO data.retrenchment VALUES (1)",
        "DROP VIEW data.retrenchment",
        "SELECT * INTO data.copy FROM data.retrenchment",
        "SELECT * FROM data.retrenchment FOR UPDATE",
        "GRANT SELECT ON data.retrenchment TO public",
    ],
)
def test_anything_but_a_read_is_refused(sql):
    _rejected(sql)


def test_a_second_statement_is_refused():
    assert "exactly one statement" in _rejected(
        "SELECT year FROM data.retrenchment; DROP TABLE datasets"
    )


def test_tables_outside_the_data_schema_are_refused():
    assert "Only views in the 'data' schema" in _rejected("SELECT * FROM datasets")
    assert "Use data.retrenchment" in _rejected("SELECT * FROM retrenchment")


def test_unknown_view_gets_a_hint():
    assert "Did you mean: retrenchment" in _rejected("SELECT * FROM data.retrenchmnt")


def test_unknown_column_gets_a_hint():
    assert "Did you mean: retrench" in _rejected("SELECT SUM(retrenched) FROM data.retrenchment")


def test_qualified_column_must_exist_in_that_view():
    msg = _rejected("SELECT t.industry FROM data.retrenchment_totals t")

    assert "View 'retrenchment_totals' has no column 'industry'" in msg


def test_summing_a_non_additive_measure_is_refused():
    assert "can't be summed" in _rejected("SELECT SUM(incidence) FROM data.retrenchment")
    assert "can't be summed" in _rejected("SELECT SUM(r.incidence * 2) FROM data.retrenchment r")


def test_side_effect_functions_are_refused():
    assert "pg_sleep" in _rejected("SELECT pg_sleep(10) FROM data.retrenchment")


def test_a_query_must_read_a_view():
    assert "at least one" in _rejected("SELECT 1")


def test_unparseable_sql_is_refused():
    assert "doesn't parse" in _rejected("SELEC year FROM")
