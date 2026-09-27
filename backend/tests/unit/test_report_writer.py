"""What the report writer is shown: every measure comes back from the views as a float, and
the LLM copies numbers as it sees them, so whole counts must reach it as 26110, not
26110.0, and long decimals as a readable number the validator can still match."""

from app.agents.nodes.report_writer import _format_analysis, _format_findings, format_number


def analysis(columns, rows):
    return {"sql": "SELECT ...", "interpretation": "", "columns": columns, "rows": rows}


def test_whole_floats_are_shown_without_decimals():
    assert format_number(26110.0) == "26110"
    assert format_number(0.0) == "0"
    assert format_number(-150.0) == "-150"


def test_long_decimals_are_rounded_but_stay_within_validator_tolerance():
    assert format_number(4123.456789012) == "4123.46"
    assert format_number(1234567.891) == "1234567.89"
    for value in (4123.456789012, 1234567.891, 3.29456789, 0.0393123456, -12.3456789):
        shown = float(format_number(value))
        assert abs(shown - value) <= abs(value) * 0.001


def test_small_shares_keep_their_significant_digits():
    assert format_number(0.0393123456) == "0.0393123"
    assert format_number(3.29456789) == "3.29457"


def test_non_floats_are_unchanged():
    assert format_number(2020) == "2020"
    assert format_number("Male") == "Male"
    assert format_number(None) == "None"
    assert format_number(True) == "True"


def test_query_result_rows_reach_the_prompt_formatted():
    text = _format_analysis(
        analysis(["year", "retrench_total", "rate"], [[2020, 26110.0, 6.123456789]])
    )
    assert "2020 | 26110 | 6.12346" in text
    assert "26110.0" not in text


def test_findings_reach_the_prompt_formatted():
    text = _format_findings(
        [
            {
                "metric_name": "retrench_total [year=2020]",
                "value": 26110.0,
                "dataset_id": "retrenchment_by_residential_status",
                "field_ref": "data.retrenchment_by_residential_status",
            }
        ]
    )
    assert "retrench_total [year=2020] = 26110 (" in text
