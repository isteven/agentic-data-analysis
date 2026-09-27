"""Chart spec: code picks the chart type from the result's shape, so the same kind of
question always gets the same chart; the planner only suggests which columns to plot.
Every answer with a number gets a chart."""

from app.agents.chart import MAX_BAR_CATEGORIES, TOP_CATEGORIES, build_chart_spec, time_columns_in
from app.data.sql_runner import QueryResult

CATALOG = {
    "v": [
        {"column": "year", "role": "time"},
        {"column": "sex", "role": "dimension"},
        {"column": "station", "role": "dimension"},
        {"column": "value", "role": "measure"},
    ]
}


def result(columns, rows):
    return QueryResult(sql="SELECT ...", columns=columns, rows=rows, truncated=False)


def spec(res, suggestion=None):
    return build_chart_spec(suggestion, res, CATALOG, ["v"])


def test_three_or_more_periods_is_a_line_whatever_the_planner_suggested():
    res = result(["year", "value"], [[2023, 1.0], [2024, 2.0], [2025, 3.0]])

    chart = spec(res, {"type": "bar", "x": "year", "y": ["value"]})

    assert (chart["type"], chart["x"], chart["y"]) == ("line", "year", ["value"])


def test_two_periods_are_a_bar():
    chart = spec(result(["year", "value"], [[2023, 3.93], [2025, 3.29]]))

    assert (chart["type"], chart["x"]) == ("bar", "year")


def test_time_series_split_by_a_dimension_is_one_line_per_group():
    rows = [[y, s, 1.0] for y in (2023, 2024, 2025) for s in ("Male", "Female")]

    chart = spec(result(["year", "sex", "value"], rows))

    assert (chart["type"], chart["x"], chart["group"], chart["y"]) == ("line", "year", "sex", ["value"])


def test_categories_are_a_bar():
    chart = spec(result(["sex", "value"], [["Male", 1.0], ["Female", 2.0]]))

    assert (chart["type"], chart["x"], chart["limit"]) == ("bar", "sex", None)


def test_too_many_categories_show_the_first_rows_in_query_order():
    rows = [[f"station {i}", float(i)] for i in range(MAX_BAR_CATEGORIES + 10)]

    chart = spec(result(["station", "value"], rows))

    assert (chart["type"], chart["x"], chart["limit"]) == ("bar", "station", TOP_CATEGORIES)


def test_a_long_time_series_is_never_cut():
    rows = [[year, 1.0] for year in range(1980, 2026)]

    chart = spec(result(["year", "value"], rows))

    assert (chart["type"], chart["limit"]) == ("line", None)


def test_a_single_labelled_value_is_one_bar():
    chart = spec(result(["year", "value"], [[2020, 14380]]))

    assert (chart["type"], chart["x"], chart["y"]) == ("bar", "year", ["value"])


def test_a_single_bare_number_is_one_bar_without_a_category():
    chart = spec(result(["total"], [[14380]]))

    assert (chart["type"], chart["x"], chart["y"]) == ("bar", None, ["total"])


def test_planner_none_is_overridden_when_there_is_a_number():
    chart = spec(result(["sex", "value"], [["Male", 1.0], ["Female", 2.0]]), {"type": "none"})

    assert chart["type"] == "bar"


def test_planner_choice_of_columns_is_kept():
    res = result(["year", "value", "other"], [[2023, 1.0, 5.0], [2024, 2.0, 6.0], [2025, 3.0, 7.0]])

    chart = spec(res, {"type": "line", "x": "year", "y": ["other"]})

    assert (chart["y"], chart["source"]) == (["other"], "planner")


def test_an_unusable_suggestion_falls_back_to_a_chart_not_to_none():
    res = result(["year", "value"], [[2023, 1.0], [2024, 2.0], [2025, 3.0]])

    chart = spec(res, {"type": "line", "x": "no_such_column", "y": ["value"]})

    assert (chart["type"], chart["x"], chart["source"]) == ("line", "year", "fallback")


def test_several_label_columns_chart_by_the_most_specific_one():
    rows = [["NUS", f"degree {i}", float(i)] for i in range(5)] + [["NTU", f"degree {i}", float(i)] for i in range(5, 9)]

    chart = spec(result(["university", "degree", "rate"], rows))

    assert (chart["type"], chart["x"], chart["y"]) == ("bar", "degree", ["rate"])


def test_a_result_with_no_number_has_no_chart():
    chart = spec(result(["university"], [["NUS"], ["NTU"]]))

    assert chart["type"] == "none"


def test_a_long_list_is_cut_to_the_end_the_question_cares_about():
    rows = [[f"station {i}", float(i)] for i in range(MAX_BAR_CATEGORIES + 10)]

    shortest = spec(result(["station", "value"], rows), {"x": "station", "y": ["value"], "best": "lowest"})
    highest = spec(result(["station", "value"], rows), {"x": "station", "y": ["value"], "best": "highest"})

    assert (shortest["limit"], shortest["sort"]) == (TOP_CATEGORIES, "asc")
    assert highest["sort"] == "desc"


def test_a_short_list_keeps_the_query_order():
    chart = spec(result(["sex", "value"], [["Male", 2.0], ["Female", 1.0]]), {"x": "sex", "y": ["value"], "best": "lowest"})

    assert chart["sort"] is None


def test_time_columns_are_the_result_columns_the_profile_marks_as_time():
    # The Data tab shows these as labels (2020, not 2,020); the role comes from the
    # profile, so any dataset's time column works without naming it.
    res = result(["year", "sex", "value"], [[2020, "Male", 1.5]])
    assert time_columns_in(res, CATALOG, ["v"]) == ["year"]


def test_no_time_columns_when_the_result_has_none():
    res = result(["station", "value"], [["Jurong East", 12.0]])
    assert time_columns_in(res, CATALOG, ["v"]) == []
