"""The full graph on the mock provider: what the load test runs, so it must complete
for real - SQL through the gate, the read-only runner, validator and persistence."""

import uuid

import pytest

from app.db.session import AsyncSessionLocal
from app.services.query_service import execute_graph

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_a_run_on_the_mock_provider_completes_grounded_and_charted(seeded_db):
    state = await execute_graph(AsyncSessionLocal, "How many retrenchments?", uuid.uuid4(), provider="mock")

    assert state["status"] == "completed"
    assert state["analysis"]["columns"] == ["row_count"]
    assert state["analysis"]["rows"][0][0] > 0  # counted by Postgres
    assert state["grounded"] is True
    assert state["analysis"]["chart"]["type"] == "bar"
    assert {c["node_name"] for c in state["llm_calls"]} == {
        "intent", "coordinator", "analytics", "report_writer", "reviewer"
    }
