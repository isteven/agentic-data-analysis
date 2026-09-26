"""Chart spec for a query result: the planner suggests columns, code picks the type,
the frontend draws.

The type follows from the result's shape, never from the model, so the same kind of
question always gets the same chart: a time axis with 3+ periods is a line; two
periods, categories or a single value are bars. Every result with a number gets a
chart. The model only chooses which columns go where; a suggestion naming a column
that isn't usable is replaced by columns picked from the result's shape. Every
plotted value comes from the database result itself.
"""

import logging

from app.data.sql_runner import QueryResult

logger = logging.getLogger(__name__)

MAX_BAR_CATEGORIES = 30  # beyond this a bar chart is unreadable...
TOP_CATEGORIES = 15  # ...so it shows this many rows, in the query's order
MAX_SERIES = 8
MIN_LINE_PERIODS = 3  # two points make a comparison (bars), not a trend
SCALE_RATIO = 20  # series sharing one axis must be within this factor of each other


def _numeric_columns(result: QueryResult) -> list[str]:
    numeric = []
    for i, name in enumerate(result.columns):
        values = [row[i] for row in result.rows if row[i] is not None]
        if values and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
            numeric.append(name)
    return numeric


def _distinct(result: QueryResult, column: str) -> int:
    i = result.columns.index(column)
    return len({row[i] for row in result.rows})


def _same_scale(result: QueryResult, y: list[str]) -> list[str]:
    """Keep the y columns on roughly the first one's scale: counts in the thousands and
    rates around 5 on one axis would flatten the rates to a line at zero. The dropped
    columns are still in the result table."""

    def peak(column: str) -> float:
        i = result.columns.index(column)
        return max((abs(r[i]) for r in result.rows if isinstance(r[i], (int, float))), default=0.0)

    if len(y) < 2:
        return y
    base = peak(y[0]) or 1.0
    return [c for c in y if base / SCALE_RATIO <= (peak(c) or base) <= base * SCALE_RATIO]


def _columns_from_shape(
    result: QueryResult, labels: list[str], values: list[str], time_columns: set[str]
) -> tuple[str | None, list[str], str | None]:
    """x, y and group picked from the result alone."""
    time = next((c for c in labels if c in time_columns), None)
    others = [c for c in labels if c != time]
    if time and not others:
        return time, values[:MAX_SERIES], None
    if time and len(others) == 1 and _distinct(result, others[0]) <= MAX_SERIES:
        return time, values[:1], others[0]
    if others:
        # Several labels (e.g. university, degree): the most specific one tells rows apart.
        x = max(others, key=lambda c: _distinct(result, c))
        return x, values[:MAX_SERIES], None
    return time, values[:MAX_SERIES], None  # a bare number: x is None


def _problem(suggestion: dict, labels: list[str], values: list[str], result: QueryResult) -> str | None:
    """Why the suggested columns can't be charted, or None if they can."""
    x, y, group = suggestion.get("x"), suggestion.get("y") or [], suggestion.get("group")
    if x not in labels:
        return f"x column {x!r} is not a label column of the result"
    if not y or any(c not in values for c in y):
        return f"y columns {y!r} must be numeric result columns"
    if group and (group not in labels or group == x):
        return f"group column {group!r} is not another label column of the result"
    if group and (len(y) != 1 or _distinct(result, group) > MAX_SERIES):
        return f"a grouped chart needs one y column and at most {MAX_SERIES} groups"
    return None


def build_chart_spec(
    suggestion: dict | None, result: QueryResult, catalog: dict[str, list[dict]], views: list[str]
) -> dict:
    """{"type": "line"|"bar"|"none", "x", "y": [...], "group", "limit", "sort", "source"}

    `limit`: draw only the first N rows (too many categories); None = all rows.
    `sort`: "asc" | "desc" by the first y column before cutting to `limit`, so the chart
    shows the end of the list the question is about (the planner's `best`) whatever
    order the SQL returned; None = query order.
    """
    time_columns = {c["column"] for v in views for c in catalog.get(v, []) if c["role"] == "time"}
    numeric = _numeric_columns(result)
    values = [c for c in numeric if c not in time_columns]
    labels = [c for c in result.columns if c not in values]
    if not values or not result.rows:
        return {
            "type": "none", "x": None, "y": [], "group": None, "limit": None, "sort": None, "source": "fallback"
        }

    problem = _problem(suggestion, labels, values, result) if suggestion else "no suggestion"
    if problem is None:
        x, y, group = suggestion["x"], list(suggestion["y"]), suggestion.get("group")
        source = "planner"
    else:
        if suggestion:
            logger.info("[DEBUG] build_chart_spec: suggestion not usable (%s): %s", problem, suggestion)
        x, y, group = _columns_from_shape(result, labels, values, time_columns)
        source = "fallback"

    over_time = x in time_columns
    chart_type = "line" if over_time and _distinct(result, x) >= MIN_LINE_PERIODS else "bar"
    too_many = x is not None and not over_time and _distinct(result, x) > MAX_BAR_CATEGORIES
    best = (suggestion or {}).get("best")
    sort = {"lowest": "asc", "highest": "desc"}.get(best) if too_many else None
    return {
        "type": chart_type,
        "x": x,
        "y": _same_scale(result, y),
        "group": group,
        "limit": TOP_CATEGORIES if too_many else None,
        "sort": sort,
        "source": source,
    }
