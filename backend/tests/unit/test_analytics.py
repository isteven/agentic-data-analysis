import pandas as pd

from app.agents.nodes.analytics import _analyze_dataset, _find_query_filters
from app.agents.state import new_state

INDUSTRY_ENTRY = {"default_slice": {"industry": ["manufacturing", "construction"]}}


def _hierarchical_retrenchment() -> pd.DataFrame:
    # 'electronic products' is a sub-industry already counted inside 'manufacturing'
    return pd.DataFrame(
        {
            "year": [2020, 2020, 2020],
            "industry": ["manufacturing", "electronic products", "construction"],
            "retrench": [100.0, 60.0, 50.0],
        }
    )


def _finding_values(state) -> dict[str, float]:
    return {f["metric_name"]: f["value"] for f in state["findings"]}


def test_unfiltered_total_does_not_double_count_sub_industries():
    state = new_state(query="show me the layoff trend", run_id="r1")

    _analyze_dataset(
        "retrench", _hierarchical_retrenchment(), state["query"], state, INDUSTRY_ENTRY
    )

    assert list(_finding_values(state).values()) == [150.0]


def test_filter_on_sub_industry_uses_only_that_row():
    state = new_state(query="retrenchment in electronic products", run_id="r1")

    _analyze_dataset(
        "retrench", _hierarchical_retrenchment(), state["query"], state, INDUSTRY_ENTRY
    )

    assert list(_finding_values(state).values()) == [60.0]


def test_query_word_female_does_not_match_male():
    df = pd.DataFrame({"sex": ["Total", "Male", "Female"], "value": [3.0, 1.0, 2.0]})

    filters = _find_query_filters("hours worked by female workers", df)

    assert filters == {"sex": "Female"}
