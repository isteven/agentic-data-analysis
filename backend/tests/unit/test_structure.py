import numpy as np
import pandas as pd

from app.data.structure import ancestor_chain, infer_structure, proves_additive, rounding_unit

YEARS = [2019, 2020, 2021, 2022, 2023, 2024]
# a separate top-level value, larger than every other value in some years, so no value
# dominates everything (that would make it a grand total rather than a parent)
OTHER = [500, 1, 500, 1, 500, 1]


def _long(values_by_label: dict[str, list[float]], years=YEARS, dim="industry") -> pd.DataFrame:
    """One row per (year, label) from per-label yearly values."""
    rows = [
        {"year": y, dim: label, "count": v}
        for label, series in values_by_label.items()
        for y, v in zip(years, series, strict=True)
    ]
    return pd.DataFrame(rows)


def test_parent_equal_to_the_sum_of_its_parts_is_found():
    a, b, c = [10, 20, 30, 40, 50, 60], [5, 7, 9, 11, 13, 15], [100, 90, 80, 70, 60, 50]
    df = _long({"a": a, "b": b, "c": c, "ab": list(np.add(a, b))})

    s = infer_structure(df, "industry", "count", "year")

    assert s["parents"] == {"a": "ab", "b": "ab"}
    assert s["exclude_values"] == []
    assert proves_additive(s)


def test_multi_level_hierarchy_is_found_level_by_level():
    a, b, c = [10, 20, 30, 40, 50, 60], [5, 7, 9, 11, 13, 15], [3, 1, 4, 1, 5, 9]
    ab = list(np.add(a, b))
    df = _long({"a": a, "b": b, "c": c, "ab": ab, "abc": list(np.add(ab, c)), "o": OTHER})

    s = infer_structure(df, "industry", "count", "year")

    assert s["parents"] == {"a": "ab", "b": "ab", "ab": "abc", "c": "abc"}
    assert ancestor_chain("a", s["parents"]) == ["abc", "ab", "a"]


def test_independent_rounding_within_tolerance_still_matches():
    # published parents and parts are rounded separately: off by one rounding unit
    a, b = [110, 220, 330, 440, 550, 660], [50, 70, 90, 110, 130, 150]
    parent = [x + y + 10 for x, y in zip(a, b, strict=True)]
    df = _long({"a": a, "b": b, "ab": parent, "o": [5000, 10, 5000, 10, 5000, 10]})

    assert infer_structure(df, "industry", "count", "year")["parents"] == {"a": "ab", "b": "ab"}


def test_grand_total_and_overlapping_bucket_are_excluded():
    low, mid, high = [10, 12, 14, 16, 18, 20], [30, 31, 32, 33, 34, 35], [5, 6, 7, 8, 9, 10]
    total = [x + y + z for x, y, z in zip(low, mid, high, strict=True)]
    # overlaps: all of `high` plus part of `mid` - not a part of the total's breakdown
    overlap = [h + 11 for h in high]
    values = {"low": low, "mid": mid, "high": high, "Total": total, "mid+": overlap}
    df = _long(values, dim="bucket")

    s = infer_structure(df, "bucket", "count", "year")

    assert s["exclude_values"] == ["Total", "mid+"]
    assert s["parents"] == {}  # the grand total's children are the top level
    assert proves_additive(s)


def test_parallel_scheme_with_less_coverage_is_dropped():
    x, y, z = [100, 200, 300, 400, 500, 600], [71, 83, 97, 64, 88, 79], [13, 27, 31, 46, 52, 68]
    df = _long({"x": x, "y": y, "z": z}, dim="occupation")
    # a second scheme covering the same whole, published only for the later years
    later = YEARS[1:]
    p = [a + b - 50 for a, b in zip(x[1:], y[1:], strict=True)]
    q = [c + 50 for c in z[1:]]
    df = pd.concat([df, _long({"p": p, "q": q}, years=later, dim="occupation")])

    s = infer_structure(df, "occupation", "count", "year")

    assert sorted(s["exclude_values"]) == ["p", "q"]


def test_era_whose_relations_are_not_a_tree_is_unverified():
    # 2006+: clean tree
    a, b = [10, 20, 30, 40, 50, 60], [5, 7, 9, 11, 13, 15]
    clean = _long(
        {"a": a, "b": b, "ab": list(np.add(a, b)), "o": OTHER}, years=list(range(2006, 2012))
    )
    # 1998-2003: a different value set where two values both equal m + n - a value with
    # two parents is what coincidental sums in thin data look like
    m, n = [101, 207, 303, 409, 511, 613], [52, 61, 47, 58, 66, 49]
    mn = list(np.add(m, n))
    old = _long({"m": m, "n": n, "c1": mn, "c2": mn}, years=list(range(1998, 2004)))

    s = infer_structure(pd.concat([old, clean]), "industry", "count", "year")

    assert s["unverified_periods"] == [[1998, 2003]]
    assert s["parents"] == {"a": "ab", "b": "ab"}


def test_rates_prove_nothing():
    rates = {"a": [91.2, 92.0, 90.5, 93.1, 94.0, 92.2], "b": [88.1, 87.5, 89.9, 90.0, 91.3, 90.8]}
    df = _long(rates)

    s = infer_structure(df, "industry", "count", "year")

    assert s is None and not proves_additive(s)


def test_works_without_a_time_column():
    a, b = [10, 20, 30, 40, 50, 60], [5, 7, 9, 11, 13, 15]
    df = _long({"a": a, "b": b, "ab": list(np.add(a, b)), "o": OTHER}).rename(
        columns={"year": "region"}
    )
    df["region"] = df["region"].astype(str)

    s = infer_structure(df, "industry", "count", None)

    assert s["parents"] == {"a": "ab", "b": "ab"}
    assert s["unverified_periods"] == []


def test_too_few_cells_is_not_evidence():
    df = _long({"a": [1, 2], "b": [3, 4], "ab": [4, 6]}, years=[2020, 2021])

    assert infer_structure(df, "industry", "count", "year") is None


def test_rounding_unit_is_the_coarsest_step_all_values_share():
    assert rounding_unit(np.array([100.0, 2300.0, 400.0])) == 100
    assert rounding_unit(np.array([10.0, 2310.0])) == 10
    assert rounding_unit(np.array([2312.2, 0.4, np.nan])) == 0.1
