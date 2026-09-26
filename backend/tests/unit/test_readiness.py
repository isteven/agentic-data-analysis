"""GET /api/health/ready: can this deployment answer a question right now? The API being
up (GET /api/health) isn't enough: it also needs Postgres, Redis and a running worker.
Logs can't tell you a worker is missing - only that nothing is being logged."""

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import health
from app.api.routes.health import get_readiness_checks


class FakeChecks:
    """Each check passes unless told how it should fail."""

    def __init__(self, **failures):
        self.failures = failures

    async def _run(self, name):
        failure = self.failures.get(name)
        if failure == "hang":
            await asyncio.sleep(60)
        elif failure:
            raise failure

    async def database(self):
        await self._run("database")

    async def redis(self):
        await self._run("redis")

    async def worker(self):
        await self._run("worker")


def get_ready(checks):
    app = FastAPI()
    app.include_router(health.router)
    app.dependency_overrides[get_readiness_checks] = lambda: checks
    return TestClient(app).get("/api/health/ready")


def test_ready_when_everything_answers():
    response = get_ready(FakeChecks())

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {"database": "ok", "redis": "ok", "worker": "ok"},
    }


def test_not_ready_names_what_is_down():
    response = get_ready(FakeChecks(redis=ConnectionError("Connection refused")))

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not ready"
    assert body["checks"]["redis"] == "ConnectionError: Connection refused"
    assert body["checks"]["database"] == "ok"


def test_not_ready_when_no_worker_is_running():
    response = get_ready(FakeChecks(worker=RuntimeError("no worker running")))

    assert response.status_code == 503
    assert response.json()["checks"]["worker"] == "RuntimeError: no worker running"


def test_a_hung_dependency_times_out_instead_of_hanging_the_probe(monkeypatch):
    monkeypatch.setattr(health, "CHECK_TIMEOUT_SECONDS", 0.05)

    response = get_ready(FakeChecks(database="hang"))

    assert response.status_code == 503
    assert response.json()["checks"]["database"] == "timed out after 0.05 s"


def test_liveness_stays_a_plain_process_check():
    # /api/health must not depend on Postgres, Redis or the worker: a probe restarting
    # the API because the worker is down would make things worse.
    app = FastAPI()
    app.include_router(health.router)

    assert TestClient(app).get("/api/health").json() == {"status": "ok"}


@pytest.mark.parametrize("workers, expected", [({}, "no worker running"), ({"w1": {}}, None)])
async def test_the_worker_check_reads_the_live_worker_registry(workers, expected):
    class Queue:
        async def info(self):
            return {"workers": workers, "queued": 0, "active": 0}

    checks = health.ReadinessChecks(engine=None, redis=None, queue=Queue())

    if expected:
        with pytest.raises(RuntimeError, match=expected):
            await checks.worker()
    else:
        await checks.worker()
