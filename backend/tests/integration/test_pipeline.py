"""The full agent graph against the real seeded database, with each node's LLM replaced
by a scripted fake - deterministic, free, and runnable in CI without API keys.

Exercises what unit tests can't: node order, state handed between agents, the SQL
running for real through the gate and read-only role, the reviewer's re-route loop,
the number check, provider fallback, and persistence.
"""

import uuid

import pytest
from langchain_core.messages import AIMessage

from app.agents import llm
from app.agents.nodes import analytics, coordinator, intent, report_writer, reviewer
from app.agents.nodes.coordinator import CoordinatorPlan, PlanStepOutput
from app.agents.nodes.intent import Intent
from app.agents.nodes.reviewer import Review
from app.db.session import AsyncSessionLocal
from app.llm.provider_factory import FallbackChatModel
from app.services.query_service import execute_graph, get_run, persist_run

pytestmark = pytest.mark.asyncio(loop_scope="session")

QUESTION = "How many residents were retrenched in 2020?"
RESIDENTS_2020 = (
    "SELECT year, retrench_resident FROM data.retrenchment_by_residential_status WHERE year = 2020"
)
TOTAL_2020 = (
    "SELECT year, retrench_total FROM data.retrenchment_by_residential_status WHERE year = 2020"
)


class Scripted:
    """A chat model that returns its scripted replies in order, whatever it's asked."""

    def __init__(self, *replies):
        self.replies = list(replies)

    def bind_tools(self, tools, **kwargs):
        return self

    def with_structured_output(self, schema, **kwargs):
        return self

    async def ainvoke(self, input, config=None, **kwargs):
        return self.replies.pop(0)


class Down:
    """A provider that is unreachable."""

    def bind_tools(self, tools, **kwargs):
        return self

    def with_structured_output(self, schema, **kwargs):
        return self

    async def ainvoke(self, input, config=None, **kwargs):
        raise ConnectionError("provider unreachable")


def plan(*dataset_ids):
    return CoordinatorPlan(steps=[PlanStepOutput(dataset_id=d, reason="relevant") for d in dataset_ids])


def submit(sql, interpretation="Residents retrenched in 2020"):
    return AIMessage(
        content="",
        tool_calls=[
            {"name": "submit_answer", "args": {"sql": sql, "interpretation": interpretation}, "id": uuid.uuid4().hex}
        ],
    )


def report(text):
    return AIMessage(content=text)


@pytest.fixture
def llms(monkeypatch):
    """Maps node name -> [(provider, model)]; each node's LLM calls use its entry, through
    the real node_model / FallbackChatModel so fallback tracing is exercised too."""
    scripts: dict[str, list[tuple[str, object]]] = {}
    real_node_model = llm.node_model

    def fake_node_model(state, node_name, model_tier):
        # Unless a test scripts it, the intent step passes the question through as-is.
        models = scripts.get(node_name) or (
            [("fake", Scripted(Intent(rewritten=state["query"], answerable=True)))]
            if node_name == "intent"
            else None
        )
        monkeypatch.setattr(
            llm,
            "get_chat_model",
            lambda provider=None, tier=None, on_fallback=None: FallbackChatModel(
                models, on_fallback
            ),
        )
        return real_node_model(state, node_name, model_tier)

    for module in (intent, coordinator, analytics, report_writer, reviewer):
        monkeypatch.setattr(module, "node_model", fake_node_model)
    return scripts


async def run(question=QUESTION):
    async with AsyncSessionLocal() as session:
        return await execute_graph(session, question, uuid.uuid4())


def trace_text(state, node=None):
    return [e["content"] for e in state["trace_events"] if node is None or e["node_name"] == node]


async def test_happy_path_answers_from_the_database_and_persists(seeded_db, llms):
    llms["coordinator"] = [("fake", Scripted(plan("retrenchment_by_residential_status")))]
    llms["analytics"] = [("fake", Scripted(submit(RESIDENTS_2020)))]
    llms["report_writer"] = [("fake", Scripted(report("14,380 residents were retrenched in 2020.")))]
    llms["reviewer"] = [("fake", Scripted(Review(verdict="pass", reason="Answers it.")))]

    state = await run()

    assert state["status"] == "completed"
    assert state["analysis"]["rows"] == [[2020, 14380]]  # computed by Postgres, not the LLM
    assert state["grounded"] is True
    nodes = list(dict.fromkeys(e["node_name"] for e in state["trace_events"]))
    assert nodes[:3] == ["intent", "coordinator", "extraction"]
    assert trace_text(state, "reviewer")[-1].startswith("Passed")

    async with AsyncSessionLocal() as session:
        run_id = uuid.UUID(state["run_id"])
        await persist_run(session, run_id, QUESTION, state)
        stored, trace = await get_run(session, run_id)
    assert stored.status == "completed"
    assert stored.completed_at is not None
    assert len(trace) == len(state["trace_events"])


async def test_reviewer_sends_a_wrong_analysis_back_to_the_planner(seeded_db, llms):
    llms["coordinator"] = [("fake", Scripted(plan("retrenchment_by_residential_status")))]
    llms["analytics"] = [("fake", Scripted(submit(TOTAL_2020, "All retrenchments"), submit(RESIDENTS_2020)))]
    llms["report_writer"] = [
        ("fake", Scripted(report("26,110 were retrenched in 2020."), report("14,380 residents were retrenched in 2020.")))
    ]
    llms["reviewer"] = [
        (
            "fake",
            Scripted(
                Review(verdict="wrong_analysis", reason="Asked for residents; this counts everyone."),
                Review(verdict="pass", reason="Answers it."),
            ),
        )
    ]

    state = await run()

    assert state["review_rounds"] == 1
    assert any(t.startswith("Sent back to analytics") for t in trace_text(state, "reviewer"))
    assert "Re-planning with the reviewer's feedback." in trace_text(state, "analytics")
    assert state["analysis"]["rows"] == [[2020, 14380]]
    assert state["report_markdown"].startswith("14,380 residents")


async def test_reviewer_gives_up_after_one_retry_with_a_visible_caveat(seeded_db, llms):
    llms["coordinator"] = [("fake", Scripted(plan("retrenchment_by_residential_status")))]
    llms["analytics"] = [("fake", Scripted(submit(TOTAL_2020), submit(TOTAL_2020)))]
    llms["report_writer"] = [("fake", Scripted(report("26,110 in 2020."), report("26,110 in 2020.")))]
    wrong = Review(verdict="wrong_analysis", reason="Counts everyone, not residents.")
    llms["reviewer"] = [("fake", Scripted(wrong, wrong))]

    state = await run()

    assert state["review_rounds"] == 1  # bounded: no endless loop
    assert "Reviewer's caveat: Counts everyone, not residents." in state["report_markdown"]


async def test_validator_flags_a_number_the_database_never_produced(seeded_db, llms):
    llms["coordinator"] = [("fake", Scripted(plan("retrenchment_by_residential_status")))]
    llms["analytics"] = [("fake", Scripted(submit(RESIDENTS_2020)))]
    # 99,999 is a hallucination: nothing in the query result supports it.
    llms["report_writer"] = [("fake", Scripted(report("About 99,999 residents were retrenched in 2020.")))]
    llms["reviewer"] = [("fake", Scripted(Review(verdict="pass", reason="ok")))]

    state = await run()

    assert state["grounded"] is False
    assert "could not be automatically verified" in state["report_markdown"]


async def test_a_failed_provider_falls_back_and_the_switch_is_traced(seeded_db, llms):
    llms["coordinator"] = [
        ("openai", Down()),
        ("bedrock", Scripted(plan("retrenchment_by_residential_status"))),
    ]
    llms["analytics"] = [("fake", Scripted(submit(RESIDENTS_2020)))]
    llms["report_writer"] = [("fake", Scripted(report("14,380 residents were retrenched in 2020.")))]
    llms["reviewer"] = [("fake", Scripted(Review(verdict="pass", reason="ok")))]

    state = await run()

    assert state["status"] == "completed"
    assert state["fallbacks"] == ["openai->bedrock"]
    assert any("openai failed (ConnectionError); retried on bedrock" in t for t in trace_text(state, "coordinator"))


async def test_no_relevant_dataset_ends_partial_not_crashed(seeded_db, llms):
    llms["coordinator"] = [("fake", Scripted(plan()))]
    llms["report_writer"] = [("fake", Scripted(report("None of the datasets cover this.")))]
    llms["reviewer"] = [("fake", Scripted())]  # nothing computed: the reviewer must not call its LLM

    state = await run("What is the GDP of Mars?")

    assert state["status"] == "partial"
    assert state["analysis"] is None


async def test_intent_declines_what_no_dataset_covers_before_any_work(seeded_db, llms):
    llms["intent"] = [
        ("fake", Scripted(Intent(rewritten="", answerable=False, reason="No GDP data is available.")))
    ]
    # No script for coordinator/analytics/writer: reaching them would raise.

    state = await run("What was Singapore's GDP growth in 2020?")

    assert state["status"] == "partial"
    assert [e["node_name"] for e in state["trace_events"]] == ["intent", "intent"]
    assert "No GDP data is available." in state["report_markdown"]


async def test_the_intent_rewrite_is_what_the_agents_work_on(seeded_db, llms):
    precise = "How many employed residents were retrenched in 2020 (resident status only)?"
    llms["intent"] = [("fake", Scripted(Intent(rewritten=precise, answerable=True)))]
    llms["coordinator"] = [("fake", Scripted(plan("retrenchment_by_residential_status")))]
    llms["analytics"] = [("fake", Scripted(submit(RESIDENTS_2020)))]
    llms["report_writer"] = [("fake", Scripted(report("14,380 residents were retrenched in 2020.")))]
    llms["reviewer"] = [("fake", Scripted(Review(verdict="pass", reason="ok")))]

    state = await run("layoffs of locals in 2020?")

    assert state["intent_query"] == precise
    assert f"Interpreted as: {precise}" in trace_text(state, "intent")
    assert state["query"] == "layoffs of locals in 2020?"  # the user's words are kept
