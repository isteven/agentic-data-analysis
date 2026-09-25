"""Data accuracy and quality: the views the planner queries must reproduce the source
publications' own figures. No LLM - this is "are the numbers right", which the
report-vs-findings validator can't see (it would pass a faithfully reported wrong sum).
"""

import pytest
from sqlalchemy import text

from app.data.manifest import DATA_ROOT, load_manifest
from app.data.parsers.excel_parser import read_mom_hours_sheet
from app.data.sql_gate import SqlRejected
from app.data.sql_runner import run_checked_sql
from app.db.session import engine

pytestmark = pytest.mark.asyncio(loop_scope="session")

MOM_VIEW = "data.mom_usual_hours_by_occupation"
RETRENCH_VIEW = "data.retrenchment_by_residential_status"


async def scalar(sql: str, **params):
    async with engine.connect() as conn:
        return (await conn.execute(text(sql), params)).scalar()


async def rows(sql: str, **params):
    async with engine.connect() as conn:
        return (await conn.execute(text(sql), params)).all()


def _mom_grand_total(year: int) -> float:
    """The Total x Total x Total cell MOM publishes in that year's sheet."""
    entry = next(e for e in load_manifest() if e.get("group") and e.get("year") == year)
    df = read_mom_hours_sheet(str(DATA_ROOT / entry["file_path"]), entry["sheet_name"])
    total = df[(df.sex == "Total") & (df.hours_bucket == "Total") & (df.occupation == "Total")]
    return float(total["value"].iloc[0])


@pytest.mark.parametrize("year", [2023, 2024, 2025])
async def test_mom_view_sums_to_the_published_grand_total(seeded_db, year):
    # Totals, the overlapping "More Than 48 Hours" band and parent rows must all be
    # gone, or this sum double-counts (it was 2x before structure inference).
    view_sum = await scalar(f"SELECT SUM(value) FROM {MOM_VIEW} WHERE year = :y", y=year)

    # Cells are published rounded to 0.1k, so allow rounding drift, not double counting.
    assert view_sum == pytest.approx(_mom_grand_total(year), rel=0.001)


async def test_mom_view_exposes_no_total_or_overlapping_rows(seeded_db):
    labels = {
        v
        for (v,) in await rows(
            f"SELECT DISTINCT sex FROM {MOM_VIEW} UNION SELECT DISTINCT hours_bucket FROM {MOM_VIEW}"
            f" UNION SELECT DISTINCT occupation FROM {MOM_VIEW}"
        )
    }

    assert "Total" not in labels
    assert "More Than 48 Hours" not in labels


async def test_mom_view_covers_every_year_file(seeded_db):
    years = [y for (y,) in await rows(f"SELECT DISTINCT year FROM {MOM_VIEW} ORDER BY year")]

    assert years == [2023, 2024, 2025]


async def test_retrenchment_2020_matches_moms_published_figures(seeded_db):
    # MOM Labour Market Report 2020: 26,110 retrenched, 14,380 of them residents.
    (row,) = await rows(
        f"SELECT retrench_total, retrench_resident, retrench_non_resident"
        f" FROM {RETRENCH_VIEW} WHERE year = 2020"
    )

    assert tuple(row) == (26110, 14380, 11730)


async def test_retrenchment_parts_add_up_to_the_total_every_year(seeded_db):
    # MOM rounds each figure to the nearest 10 independently, so the parts may miss the
    # rounded total by one rounding unit (seen: 6 years at +/-10) - never by more.
    mismatched = await rows(
        f"SELECT year FROM {RETRENCH_VIEW}"
        " WHERE ABS(retrench_resident + retrench_non_resident - retrench_total) > 10"
    )

    assert mismatched == []


async def test_graduate_employment_rates_are_percentages(seeded_db):
    out_of_range = await scalar(
        "SELECT COUNT(*) FROM data.graduate_employment_survey"
        " WHERE employment_rate_overall NOT BETWEEN 0 AND 100"
    )

    assert out_of_range == 0


async def test_missing_values_are_null_not_zero(seeded_db):
    # MOM marks suppressed cells "-"; they must stay unknown, not become 0 and drag sums.
    zeros = await scalar(f"SELECT COUNT(*) FROM {MOM_VIEW} WHERE value = 0")

    assert zeros == 0


async def test_every_manifest_dataset_is_seeded(seeded_db):
    seeded = {k for (k,) in await rows("SELECT dataset_key FROM datasets")}

    assert {e["id"] for e in load_manifest()} <= seeded


async def test_planner_sql_cannot_write(seeded_db, catalog):
    with pytest.raises(SqlRejected):
        await run_checked_sql(engine, f"DELETE FROM {RETRENCH_VIEW}", catalog)


async def test_reader_role_cannot_write_even_past_the_gate(seeded_db):
    # Defence in depth: if the sqlglot gate were bypassed, the role planner SQL runs
    # as still has no write privilege on the stored rows.
    async with engine.connect() as conn, conn.begin():
        await conn.exec_driver_sql("SET LOCAL ROLE data_reader")
        with pytest.raises(Exception, match="permission denied"):
            await conn.exec_driver_sql("DELETE FROM dataset_records")
