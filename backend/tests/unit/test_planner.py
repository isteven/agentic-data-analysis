from langchain_core.messages import AIMessage, ToolMessage

from app.agents.planner import describe, run_planner
from app.data.sql_gate import SqlRejected
from app.data.sql_runner import QueryResult

CATALOG = {
    "retrenchment": [
        {"column": "year", "role": "time", "min": 2007, "max": 2025},
        {"column": "industry", "role": "dimension", "values": ["construction", "wholesale trade"]},
        {"column": "industry_level_1", "role": "dimension", "level_of": "industry"},
        {"column": "retrench", "role": "measure", "additive": True, "unit": "persons"},
        {"column": "incidence", "role": "measure", "additive": False},
    ],
    "hidden": [{"column": "x", "role": "measure", "additive": True}],
}
RESULT = QueryResult(
    sql="SELECT ...", columns=["year", "total"], rows=[[2020, 26110]], truncated=False
)


class ScriptedModel:
    """Stands in for a chat model: returns the scripted replies in order."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.seen = []

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        self.seen.append(list(messages))
        return self.replies.pop(0)


def _call(name, **args):
    _call.n = getattr(_call, "n", 0) + 1
    return {"name": name, "args": args, "id": f"call_{_call.n}"}


def _say(*calls, text=""):
    return AIMessage(content=text, tool_calls=list(calls))


class FakeRunner:
    def __init__(self, reject=()):
        self.reject = set(reject)
        self.queries = []

    async def __call__(self, sql):
        self.queries.append(sql)
        if sql in self.reject:
            raise SqlRejected(f"bad query: {sql}")
        return RESULT


async def _run(replies, runner=None, **kw):
    trace = []
    model = ScriptedModel(replies)
    result = await run_planner(
        "retrenchments in 2020?",
        ["retrenchment"],
        CATALOG,
        model,
        runner or FakeRunner(),
        lambda kind, text: trace.append((kind, text)),
        **kw,
    )
    return result, trace, model


async def test_explores_then_submits_and_the_answer_comes_from_the_database():
    result, trace, _ = await _run(
        [
            _say(_call("describe_view", view="retrenchment"), text="Check the columns first."),
            _say(_call("run_sql", sql="SELECT DISTINCT year FROM data.retrenchment")),
            _say(
                _call("submit_answer", sql="SELECT 1", interpretation="Total retrenchments in 2020")
            ),
        ]
    )

    assert result.status == "answered"
    assert result.result is RESULT and result.interpretation == "Total retrenchments in 2020"
    assert [t["tool"] for t in result.tool_log] == ["describe_view", "run_sql", "submit_answer"]
    kinds = [k for k, _ in trace]
    assert kinds[:3] == ["reasoning", "action", "observation"]  # Reason -> Act -> Observe


async def test_rejected_query_is_fed_back_so_the_planner_can_fix_it():
    runner = FakeRunner(reject={"SELECT SUM(incidence) FROM data.retrenchment"})

    result, _, model = await _run(
        [
            _say(_call("run_sql", sql="SELECT SUM(incidence) FROM data.retrenchment")),
            _say(
                _call(
                    "submit_answer",
                    sql="SELECT AVG(incidence) FROM data.retrenchment",
                    interpretation="i",
                )
            ),
        ],
        runner,
    )

    feedback = [m for m in model.seen[1] if isinstance(m, ToolMessage)][-1]
    assert "Rejected: bad query" in feedback.content
    assert result.status == "answered" and result.queries_rejected == 1


async def test_rejected_final_query_does_not_end_the_run():
    runner = FakeRunner(reject={"bad"})

    result, _, _ = await _run(
        [
            _say(_call("submit_answer", sql="bad", interpretation="i")),
            _say(_call("submit_answer", sql="good", interpretation="i")),
        ],
        runner,
    )

    assert result.status == "answered" and runner.queries == ["bad", "good"]


async def test_cannot_answer_stops_with_a_reason():
    result, _, _ = await _run([_say(_call("cannot_answer", reason="no forecast data"))])

    assert result.status == "cannot_answer" and result.reason == "no forecast data"


async def test_step_cap_ends_a_run_that_never_commits():
    loop = [_say(_call("run_sql", sql="SELECT 1")) for _ in range(5)]

    result, _, _ = await _run(loop, max_steps=3)

    assert result.status == "gave_up" and result.steps == 3


async def test_a_model_that_stops_calling_tools_is_nudged_once_then_gives_up():
    result, _, model = await _run([_say(), _say()])

    assert result.status == "gave_up" and len(model.seen) == 2


async def test_only_selected_views_are_visible():
    runner = FakeRunner()

    _, _, model = await _run(
        [
            _say(_call("describe_view", view="hidden")),
            _say(_call("cannot_answer", reason="x")),
        ],
        runner,
    )

    feedback = [m for m in model.seen[1] if isinstance(m, ToolMessage)][-1]
    assert "No view 'hidden'" in feedback.content
    assert "hidden" not in model.seen[0][1].content  # not in the opening overview either


def test_description_marks_what_can_be_summed_and_hierarchy_levels():
    text = describe("retrenchment", CATALOG)

    assert "retrench (measure, summable, unit: persons)" in text
    assert "incidence (measure, not summable)" in text
    assert "industry_level_1 (dimension) hierarchy level of industry; 1 = top." in text
    assert '"wholesale trade"' in text


# --- Time range: a question over a span of periods must be answered per period ---

COLLAPSED = "SELECT SUM(retrench) AS change FROM data.retrenchment"
PER_YEAR = "SELECT year, SUM(retrench) AS total FROM data.retrenchment GROUP BY year"
RESULTS = {
    COLLAPSED: QueryResult(sql=COLLAPSED, columns=["change"], rows=[[-1090]], truncated=False),
    PER_YEAR: QueryResult(
        sql=PER_YEAR, columns=["year", "total"], rows=[[2015, 15580], [2025, 14490]], truncated=False
    ),
}


class ResultsRunner:
    async def __call__(self, sql):
        return RESULTS[sql]


def _submit(sql):
    return _say(_call("submit_answer", sql=sql, interpretation="Retrenchments 2015-2025"))


async def test_a_time_range_answer_collapsed_to_one_value_is_sent_back_once():
    result, trace, _ = await _run(
        [_submit(COLLAPSED), _submit(PER_YEAR)],
        runner=ResultsRunner(),
        time_range={"start": 2015, "end": 2025},
    )

    assert result.status == "answered"
    assert result.result.columns == ["year", "total"]
    sent_back = [text for kind, text in trace if kind == "observation" and "one row per" in text]
    assert len(sent_back) == 1 and "2015" in sent_back[0] and "year" in sent_back[0]


async def test_the_time_range_is_sent_back_only_once_then_accepted():
    result, _, _ = await _run(
        [_submit(COLLAPSED), _submit(COLLAPSED)],
        runner=ResultsRunner(),
        time_range={"start": 2015, "end": 2025},
    )

    assert result.status == "answered"
    assert result.result.columns == ["change"]  # an answer beats no answer


async def test_the_planner_is_told_the_time_range_up_front():
    _, _, model = await _run([_submit(PER_YEAR)], runner=ResultsRunner(), time_range={"start": 2015, "end": 2025})

    first_prompt = model.seen[0][1].content
    assert "2015" in first_prompt and "2025" in first_prompt


async def test_without_a_time_range_a_single_value_is_fine():
    result, trace, _ = await _run([_submit(COLLAPSED)], runner=ResultsRunner())

    assert result.result.columns == ["change"]
    assert not any("one row per" in text for _, text in trace)


async def test_the_time_range_is_not_enforced_on_views_without_a_time_column():
    catalog = {"stations": [{"column": "station", "role": "dimension"}, {"column": "minutes", "role": "measure"}]}
    sql = "SELECT MIN(minutes) AS m FROM data.stations"
    runner_result = QueryResult(sql=sql, columns=["m"], rows=[[1.35]], truncated=False)

    class Runner:
        async def __call__(self, q):
            return runner_result

    result = await run_planner(
        "shortest travel time since 2015?",
        ["stations"],
        catalog,
        ScriptedModel([_say(_call("submit_answer", sql=sql, interpretation="x"))]),
        Runner(),
        lambda kind, text: None,
        time_range={"start": 2015, "end": 2025},
    )

    assert result.status == "answered"
