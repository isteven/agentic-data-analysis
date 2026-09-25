"""Checks LLM-written SQL before it reaches Postgres.

The planner may write any read-only query over the generated `data` views. This gate is
the code-side guarantee that it stays that: one SELECT, only known views and columns, no
SUM over a measure the data doesn't prove additive, no side-effect functions. Rejections
are worded for the planner to act on (they become its observation), with "did you mean"
hints. What runs is the SQL regenerated from the checked parse tree, never the raw text,
so the query executed is exactly the query checked.

The runner (sql_runner.py) adds the rest: read-only transaction, the data_reader role,
a statement timeout and a row cap.
"""

import difflib

import sqlglot
from sqlglot import exp

VIEW_SCHEMA = "data"

_FORBIDDEN_NODES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.TruncateTable,
    exp.Command,  # anything sqlglot can't model (COPY, SET, GRANT, ...)
    exp.Into,  # SELECT ... INTO creates a table
    exp.Lock,  # FOR UPDATE / FOR SHARE
)
# Side-effect or introspection functions; writes are also blocked by the read-only
# transaction, this just gives the planner a clear message instead of a DB error.
_FORBIDDEN_FUNCTION_PREFIXES = ("pg_", "lo_", "dblink", "set_config", "current_setting", "txid_")


class SqlRejected(ValueError):
    """The query was refused; the message says why and how to fix it."""


def _hint(name: str, options) -> str:
    close = difflib.get_close_matches(name, sorted(options), n=3, cutoff=0.5)
    return f" Did you mean: {', '.join(close)}?" if close else ""


def _parse(sql: str) -> exp.Expression:
    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except sqlglot.errors.ParseError as exc:
        raise SqlRejected(f"The SQL doesn't parse: {exc}") from exc
    if len(statements) != 1:
        raise SqlRejected(f"Send exactly one statement; got {len(statements)}.")
    tree = statements[0]
    if not isinstance(tree, exp.Query):
        raise SqlRejected(f"Only SELECT queries are allowed; got {tree.key.upper()}.")
    for node in tree.walk():
        if isinstance(node, _FORBIDDEN_NODES):
            raise SqlRejected(f"Only read-only SELECT is allowed; found {node.key.upper()}.")
    return tree


def _referenced_views(tree: exp.Expression, catalog: dict[str, list[dict]]) -> dict[str, str]:
    """alias (or view name) -> view name, for every table the query reads."""
    cte_names = {cte.alias_or_name for cte in tree.find_all(exp.CTE)}
    views: dict[str, str] = {}
    for table in tree.find_all(exp.Table):
        name, schema = table.name, table.db
        if not schema and name in cte_names:
            continue
        if schema != VIEW_SCHEMA:
            where = f"'{schema}.{name}'" if schema else f"'{name}'"
            hint = f" Use {VIEW_SCHEMA}.{name}." if name in catalog else _hint(name, catalog)
            raise SqlRejected(
                f"Only views in the '{VIEW_SCHEMA}' schema can be read, not {where}.{hint}"
            )
        if name not in catalog:
            raise SqlRejected(f"There is no view '{VIEW_SCHEMA}.{name}'.{_hint(name, catalog)}")
        views[table.alias_or_name] = name
    return views


def _check_functions(tree: exp.Expression) -> None:
    for func in tree.find_all(exp.Func):
        name = (func.name if isinstance(func, exp.Anonymous) else func.sql_name()).lower()
        if name.startswith(_FORBIDDEN_FUNCTION_PREFIXES):
            raise SqlRejected(f"Function '{name}' isn't allowed.")


def _defined_aliases(tree: exp.Expression) -> set[str]:
    """Names the query itself defines: SELECT aliases, CTE and subquery column lists."""
    names = {a.alias for a in tree.find_all(exp.Alias) if a.alias}
    for table_alias in tree.find_all(exp.TableAlias):
        names.update(c.name for c in table_alias.columns)
    for cte in tree.find_all(exp.CTE):
        if isinstance(cte.this, exp.Query):
            names.update(s.alias_or_name for s in cte.this.selects)
    for sub in tree.find_all(exp.Subquery):
        if isinstance(sub.this, exp.Query):
            names.update(s.alias_or_name for s in sub.this.selects)
    return names


def _check_columns(tree, views: dict[str, str], catalog: dict[str, list[dict]]) -> None:
    known = {c["column"] for view in set(views.values()) for c in catalog[view]}
    allowed = known | _defined_aliases(tree)
    for column in tree.find_all(exp.Column):
        if isinstance(column.this, exp.Star):
            continue
        name, qualifier = column.name, column.table
        if qualifier in views:
            view_columns = {c["column"] for c in catalog[views[qualifier]]}
            if name not in view_columns:
                raise SqlRejected(
                    f"View '{views[qualifier]}' has no column '{name}'.{_hint(name, view_columns)}"
                )
        elif name not in allowed:
            raise SqlRejected(f"Unknown column '{name}'.{_hint(name, known)}")


def _check_sums(tree, views: dict[str, str], catalog: dict[str, list[dict]]) -> None:
    """Summing a rate, mean or median gives a meaningless number that looks real."""

    def non_additive(view: str, name: str) -> bool:
        return any(
            c["column"] == name and c["role"] == "measure" and not c.get("additive")
            for c in catalog[view]
        )

    for total in tree.find_all(exp.Sum):
        for column in total.find_all(exp.Column):
            name = column.name
            candidates = (
                [views[column.table]]
                if column.table in views
                else [
                    v for v in set(views.values()) if any(c["column"] == name for c in catalog[v])
                ]
            )
            if candidates and all(non_additive(v, name) for v in candidates):
                raise SqlRejected(
                    f"'{name}' can't be summed: nothing in the data shows it adds up "
                    "(rates, means and medians don't). Use AVG, MIN, MAX or report values "
                    "per row instead."
                )


def check_sql(sql: str, catalog: dict[str, list[dict]]) -> str:
    """Return the SQL to run, or raise SqlRejected. `catalog` is view name -> columns
    (app.data.views.view_catalog)."""
    tree = _parse(sql)
    views = _referenced_views(tree, catalog)
    if not views:
        raise SqlRejected(f"The query must read at least one '{VIEW_SCHEMA}' view.")
    _check_functions(tree)
    _check_columns(tree, views, catalog)
    _check_sums(tree, views, catalog)
    return tree.sql(dialect="postgres")
