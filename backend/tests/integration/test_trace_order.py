"""A run's trace is read back in the order it was emitted. All of a run's trace rows are
inserted in one transaction, so they share one created_at (Postgres now() is the
transaction start): ordering by time gave no defined order."""

import random
import uuid

import pytest

from app.agents.state import new_state
from app.db.session import AsyncSessionLocal
from app.models.agent_trace import AgentTrace
from app.models.analysis_run import AnalysisRun
from app.services.query_service import get_run, persist_run

pytestmark = pytest.mark.asyncio(loop_scope="session")


def events(n):
    return [{"node_name": "planner", "step_type": "action", "content": f"step {i}"} for i in range(n)]


async def test_trace_comes_back_in_emission_order_whatever_the_storage_order(seeded_db):
    run_id = uuid.uuid4()
    rows = [AgentTrace(run_id=run_id, seq=i, **e) for i, e in enumerate(events(12))]
    random.Random(7).shuffle(rows)  # stored out of order, all with one timestamp

    async with AsyncSessionLocal() as session:
        session.add(AnalysisRun(id=run_id, query_text="q", status="completed"))
        await session.flush()
        session.add_all(rows)
        await session.commit()
        _, trace = await get_run(session, run_id)

    assert [t["content"] for t in trace] == [f"step {i}" for i in range(12)]


async def test_saving_a_run_numbers_its_trace_in_order(seeded_db):
    run_id = uuid.uuid4()
    state = new_state("q", str(run_id))
    state["status"] = "completed"
    state["trace_events"] = events(5)

    async with AsyncSessionLocal() as session:
        await persist_run(session, run_id, "q", state)
        _, trace = await get_run(session, run_id)

    assert [t["content"] for t in trace] == [f"step {i}" for i in range(5)]
