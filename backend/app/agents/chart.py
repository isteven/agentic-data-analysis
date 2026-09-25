"""Chart spec for a query result: the planner suggests, code checks, the frontend draws.

The model only chooses how to show the result (type and which columns go where); every
plotted value comes from the database result itself. A suggestion naming a column that
isn't in the result, or plotting a non-numeric column, is replaced by a fallback picked
from the result's shape, so a bad suggestion never breaks the report.
"""

import logging

from app.data.sql_runner import QueryResult

logger = logging.getLogger(__name__)

CHART_TYPES = ("line", "bar", "none")
MAX_BAR_CATEGORIES = 30  # beyond this a bar chart is unreadable; show the table
MAX_SERIES = 8
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


def _fallback(result: QueryResult, time_columns: set[str]) -> dict:
    numeric = _numeric_columns(result)
    labels = [c for c in result.columns if c not in numeric or c in time_columns]
    values = [c for c in numeric if c not in time_columns]
    if not values or len(result.rows) < 2:
        return {"type": "none"}
    time = next((c for c in result.columns if c in time_columns), None)
    others = [c for c in labels if c != time]
    if time and len(others) <= 1:
        group = others[0] if others and _distinct(result, others[0]) <= MAX_SERIES else None
        if others and group is None:
            return {"type": "none"}
        return {
            "type": "line",
            "x": time,
            "y": values[:MAX_SERIES] if not group else values[:1],
            "group": group,
        }
    if len(labels) == 1 and _distinct(result, labels[0]) <= MAX_BAR_CATEGORIES:
        return {"type": "bar", "x": labels[0], "y": values[:MAX_SERIES], "group": None}
    return {"type": "none"}


def _problem(suggestion: dict, result: QueryResult) -> str | None:
    """Why a suggestion can't be drawn from this result, or None if it can."""
    if suggestion.get("type") not in CHART_TYPES:
        return f"unknown type {suggestion.get('type')!r}"
    if suggestion["type"] == "none":
        return None
    numeric = set(_numeric_columns(result))
    x, y, group = suggestion.get("x"), suggestion.get("y") or [], suggestion.get("group")
    if x not in result.columns:
        return f"x column {x!r} not in the result"
    if not y or any(c not in numeric for c in y):
        return f"y columns {y!r} must be numeric result columns"
    if group and group not in result.columns:
        return f"group column {group!r} not in the result"
    if group and (len(y) != 1 or _distinct(result, group) > MAX_SERIES):
        return "a grouped chart needs one y column and at most 8 groups"
    if suggestion["type"] == "bar" and _distinct(result, x) > MAX_BAR_CATEGORIES:
        return "too many categories for a bar chart"
    return None


def build_chart_spec(
    suggestion: dict | None, result: QueryResult, catalog: dict[str, list[dict]], views: list[str]
) -> dict:
    """{"type": "line"|"bar"|"none", "x", "y": [...], "group", "source": "planner"|"fallback"}"""
    time_columns = {c["column"] for v in views for c in catalog.get(v, []) if c["role"] == "time"}
    if suggestion:
        problem = _problem(suggestion, result)
        if problem is None:
            spec = {
                "type": suggestion["type"],
                "x": suggestion.get("x"),
                "y": _same_scale(result, list(suggestion.get("y") or [])),
                "group": suggestion.get("group"),
            }
            return {**spec, "source": "planner"}
        logger.info(
            "[DEBUG] build_chart_spec: planner suggestion rejected (%s): %s", problem, suggestion
        )
    spec = _fallback(result, time_columns)
    if spec.get("y"):
        spec["y"] = _same_scale(result, spec["y"])
    return {**spec, "source": "fallback"}
