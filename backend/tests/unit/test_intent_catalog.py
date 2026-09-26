"""The intent step's dataset catalog: enough to tell "not in the data" from "in the data
under other words". Declining a question the data covers is as wrong as a bad answer."""

from app.agents.nodes.intent import _catalog

MANIFEST = [{"id": "hours", "title": "Usual Hours Worked", "table": "hours"}]


def views(values_for_band, degrees):
    return {
        "hours": [
            {"column": "year", "role": "time", "min": 2023, "max": 2025},
            {"column": "hours_bucket", "role": "dimension", "values": values_for_band, "distinct": len(values_for_band)},
            {"column": "degree", "role": "dimension", "values": degrees[:20], "distinct": len(degrees)},
            {"column": "value", "role": "measure", "description": "Employed residents, thousands"},
        ]
    }


def catalog(**kw):
    return _catalog(MANIFEST, views(**kw))


def test_small_dimensions_list_their_values():
    text = catalog(values_for_band=["Under 35 Hours", "35-44 Hours", "60 Hours & Over"], degrees=["BSc"])

    # Without the values the model declined "how many worked 60+ hours" as not in the data.
    assert "hours_bucket (Under 35 Hours, 35-44 Hours, 60 Hours & Over)" in text


def test_large_dimensions_stay_names_only():
    text = catalog(values_for_band=["A"], degrees=[f"Degree {i}" for i in range(400)])

    assert "degree" in text and "Degree 1" not in text
