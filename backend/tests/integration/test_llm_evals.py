"""LLM evaluations: the real pipeline, real model, real database.

Each question runs N times (LLM_EVAL_RUNS, default 3) and every run must:
  - accuracy:      contain the expected value in the query result. Expected values are
                   MOM's published figures or computed by SQL straight from the views,
                   never from the model;
  - consistency:   reach that same answer on every run;
  - no hallucination: never leave an ungrounded number in the report (validator), and
                   decline a question the data can't answer instead of inventing one.

Costs real API calls, so it's opt-in:
    RUN_LLM_EVALS=1 TEST_DATABASE_URL=... PYTHONPATH=. uv run pytest tests/integration/test_llm_evals.py -s
Writes a per-run results table to llm-eval-results.json (quoted in TESTING.md).
"""

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pytest
from sqlalchemy import text

from app.db.session import AsyncSessionLocal, engine
from app.services.query_service import execute_graph

pytestmark = [
    pytest.mark.asyncio(loop_scope="session"),
    pytest.mark.skipif(os.environ.get("RUN_LLM_EVALS") != "1", reason="RUN_LLM_EVALS=1 not set"),
]

RUNS = int(os.environ.get("LLM_EVAL_RUNS", "3"))
RESULTS_FILE = Path(__file__).resolve().parents[2] / "llm-eval-results.json"


@dataclass
class Case:
    id: str
    question: str
    expected: float | str | None  # None = unanswerable, must be declined
    truth_sql: str | None = None  # computes `expected` from the views when set


CASES = [
    Case("residents_2020", "How many residents were retrenched in 2020?", 14380),  # MOM published
    Case("total_2009", "What was the total number of retrenchments in 2009?", 23430),  # MOM published
    Case(
        "hours_60_plus_2025",
        "How many employed residents worked 60 hours or more per week in 2025?",
        None,
        "SELECT SUM(value) FROM data.mom_usual_hours_by_occupation"
        " WHERE year = 2025 AND hours_bucket = '60 Hours & Over'",
    ),
    Case(
        "station_count",
        "How many MRT or LRT stations are in the junior college travel data?",
        None,
        'SELECT COUNT(DISTINCT "From") FROM data.mrt_to_junior_college_travel',
    ),
    Case(
        "top_university_2023",
        "Which university had the highest average overall employment rate across its degrees in 2023?",
        None,
        "SELECT university FROM data.graduate_employment_survey WHERE year = 2023"
        " GROUP BY university ORDER BY AVG(employment_rate_overall) DESC LIMIT 1",
    ),
    Case(
        # Multi-step: a share (out of all employed women) compared across two years.
        # The fast-tier planner ran out of steps on this; the 2025 share must be present.
        "women_60_plus_share",
        "How did the share of women working 60+ hours change from 2023 to 2025?",
        None,
        "SELECT 100.0 * SUM(value) FILTER (WHERE hours_bucket = '60 Hours & Over') / SUM(value)"
        " FROM data.mom_usual_hours_by_occupation WHERE year = 2025 AND sex = 'Female'",
    ),
    Case(
        # Natural wording: the data has one row per degree, so "which university" must be
        # answered per university (average across its degrees), not by the top degree row.
        "top_university_natural",
        "Which university had the highest graduate employment rate in 2023?",
        None,
        "SELECT university FROM data.graduate_employment_survey WHERE year = 2023"
        " GROUP BY university ORDER BY AVG(employment_rate_overall) DESC LIMIT 1",
    ),
    Case("gdp_unanswerable", "What was Singapore's GDP growth rate in 2020?", None),
]


@dataclass
class RunResult:
    case: str
    run: int
    status: str
    correct: bool
    grounded: bool | None
    declined: bool
    review_rounds: int
    fallbacks: list[str]
    seconds: float
    sql: str | None
    rows: list = field(default_factory=list)


_results: list[RunResult] = []


def _matches(cell, expected: float | str) -> bool:
    if isinstance(expected, str):
        return isinstance(cell, str) and cell.strip().lower() == expected.strip().lower()
    # within rounding, not a different figure
    return isinstance(cell, int | float) and abs(cell - expected) <= 0.005 * abs(expected)


def _contains(rows: list[list], expected: float | str) -> bool:
    return any(_matches(cell, expected) for row in rows for cell in row)


async def _expected(case: Case):
    if case.truth_sql is None:
        return case.expected
    async with engine.connect() as conn:
        value = (await conn.execute(text(case.truth_sql))).scalar()
    return value if isinstance(value, str) else float(value)  # SUM comes back as Decimal


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
async def test_llm_eval(seeded_db, case):
    answerable = case.expected is not None or case.truth_sql is not None
    expected = await _expected(case) if answerable else None

    for run in range(1, RUNS + 1):
        started = time.monotonic()
        async with AsyncSessionLocal() as session:
            state = await execute_graph(session, case.question, uuid.uuid4())
        analysis = state.get("analysis") or {}
        rows = analysis.get("rows") or []
        declined = not rows
        _results.append(
            RunResult(
                case=case.id,
                run=run,
                status=state["status"],
                correct=_contains(rows, expected) if answerable else declined,
                grounded=state.get("grounded"),
                declined=declined,
                review_rounds=state.get("review_rounds", 0),
                fallbacks=state.get("fallbacks", []),
                seconds=round(time.monotonic() - started, 1),
                sql=analysis.get("sql"),
                rows=rows[:5],
            )
        )

    mine = [r for r in _results if r.case == case.id]
    RESULTS_FILE.write_text(json.dumps([asdict(r) for r in _results], indent=2, default=str))
    summary = ", ".join(f"run {r.run}: {'ok' if r.correct else 'WRONG'} ({r.seconds}s)" for r in mine)
    print(f"\n[{case.id}] expected={expected!r} -> {summary}")

    assert all(r.correct for r in mine), f"accuracy/consistency failed: {[asdict(r) for r in mine]}"
    assert not any(r.grounded is False for r in mine), "a report contained ungrounded numbers"
