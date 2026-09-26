"""POST /api/queries spends LLM money on every call, on an endpoint with no login: it is
rate-limited per client, only real providers can be chosen, and the question must be
a sensible length."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.rate_limit import RateLimiter, get_rate_limiter
from app.api.routes import queries
from app.db.session import get_session
from app.models.analysis_run import AnalysisRun


class FakeRedis:
    """INCR/EXPIRE on a dict, like Redis."""

    def __init__(self, fail: bool = False):
        self.counts: dict[str, int] = {}
        self.fail = fail

    async def incr(self, key):
        if self.fail:
            raise ConnectionError("redis unreachable")
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key, seconds):
        pass


@pytest.fixture
def api(monkeypatch):
    """The queries router with its database, queue and limiter swapped for fakes."""
    submitted = []

    async def create_run(session, run_id, query_text, provider):
        submitted.append(query_text)
        return AnalysisRun(id=run_id, query_text=query_text, status="running")

    async def enqueue(*args, **kwargs):
        pass

    async def no_session():
        yield object()

    monkeypatch.setattr(queries, "create_run", create_run)
    monkeypatch.setattr(queries.queue, "enqueue", enqueue)
    app = FastAPI()
    app.include_router(queries.router)
    app.dependency_overrides[get_session] = no_session

    def with_limit(per_minute: int, redis: FakeRedis | None = None):
        limiter = RateLimiter(redis or FakeRedis(), per_minute, clock=lambda: 1_000_000.0)
        app.dependency_overrides[get_rate_limiter] = lambda: limiter
        return TestClient(app)

    return with_limit, submitted


def ask(client, **body):
    return client.post("/api/queries", json={"query": "How many?", **body})


# --- Rate limit ----------------------------------------------------------------


def test_questions_over_the_limit_get_429_with_retry_after(api):
    with_limit, submitted = api
    client = with_limit(per_minute=3)

    statuses = [ask(client).status_code for _ in range(4)]

    assert statuses == [202, 202, 202, 429]
    assert len(submitted) == 3  # the rejected one never reached the database or queue
    limited = ask(client)
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) > 0
    assert "Too many questions" in limited.json()["detail"]


def test_a_limit_of_zero_turns_it_off(api):
    with_limit, _ = api
    client = with_limit(per_minute=0)

    assert all(ask(client).status_code == 202 for _ in range(20))


def test_if_redis_is_down_questions_still_go_through(api):
    # Failing open: the limiter mustn't be what takes the app down.
    with_limit, _ = api
    client = with_limit(per_minute=1, redis=FakeRedis(fail=True))

    assert [ask(client).status_code for _ in range(3)] == [202, 202, 202]


async def test_each_client_and_each_minute_has_its_own_count():
    now = [60.0 * 1000]
    limiter = RateLimiter(FakeRedis(), per_minute=1, clock=lambda: now[0])

    assert await limiter.retry_after("10.0.0.1") is None
    assert await limiter.retry_after("10.0.0.2") is None  # another client
    assert await limiter.retry_after("10.0.0.1") is not None  # same client, same minute
    now[0] += 60
    assert await limiter.retry_after("10.0.0.1") is None  # next minute


# --- Request validation --------------------------------------------------------


@pytest.mark.parametrize("provider", ["mock", "azure_openai", "vertex_ai", "anything"])
def test_only_real_providers_can_be_chosen(api, provider):
    with_limit, submitted = api

    response = ask(with_limit(per_minute=0), provider=provider)

    assert response.status_code == 422
    assert submitted == []


@pytest.mark.parametrize("provider", ["openai", "bedrock", None])
def test_the_real_providers_or_the_default_are_accepted(api, provider):
    with_limit, _ = api

    assert ask(with_limit(per_minute=0), provider=provider).status_code == 202


@pytest.mark.parametrize("query", ["", "   ", "x" * 2001])
def test_empty_or_overlong_questions_are_rejected(api, query):
    with_limit, submitted = api

    response = with_limit(per_minute=0).post("/api/queries", json={"query": query})

    assert response.status_code == 422
    assert submitted == []
