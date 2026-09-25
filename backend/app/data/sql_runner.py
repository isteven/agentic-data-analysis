"""Runs planner SQL: gate-checked, then executed by Postgres with no way to change data.

Layers, each enough on its own to stop a write: the gate (sql_gate.py) only lets a
SELECT over the `data` views through; the transaction is READ ONLY; it runs as the
data_reader role, which can read nothing but those views. A statement timeout and a row
cap bound the cost of a bad query.
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.data.sql_gate import SqlRejected, check_sql
from app.data.views import READER_ROLE

logger = logging.getLogger(__name__)

ROW_CAP = 500  # aggregates should be small; a big result means the query didn't aggregate
STATEMENT_TIMEOUT_MS = 5000


@dataclass
class QueryResult:
    sql: str  # what actually ran (regenerated from the checked parse tree)
    columns: list[str]
    rows: list[list]
    truncated: bool


def _json_native(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


async def run_checked_sql(
    engine: AsyncEngine, sql: str, catalog: dict[str, list[dict]], row_cap: int = ROW_CAP
) -> QueryResult:
    """Check, then run. Raises SqlRejected for a refused query or a database error - both
    are something the planner can fix, so both come back as its observation."""
    checked = check_sql(sql, catalog)
    # its own connection: planner queries never share a transaction with app writes
    async with engine.connect() as conn:
        tx = await conn.begin()
        try:
            await conn.exec_driver_sql("SET TRANSACTION READ ONLY")
            await conn.exec_driver_sql(f"SET LOCAL ROLE {READER_ROLE}")
            await conn.exec_driver_sql(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}")
            # exec_driver_sql: no ":name" bind-parameter parsing of LLM-written text
            result = await conn.exec_driver_sql(checked)
            columns = list(result.keys())
            fetched = result.fetchmany(row_cap + 1)
        except DBAPIError as exc:
            message = str(exc.orig).splitlines()[0] if exc.orig else str(exc)
            logger.info(
                "[DEBUG] run_checked_sql: database refused query: %s | %s", message, checked
            )
            raise SqlRejected(f"Postgres rejected the query: {message}") from exc
        finally:
            await tx.rollback()
    return QueryResult(
        sql=checked,
        columns=columns,
        rows=[[_json_native(v) for v in row] for row in fetched[:row_cap]],
        truncated=len(fetched) > row_cap,
    )
