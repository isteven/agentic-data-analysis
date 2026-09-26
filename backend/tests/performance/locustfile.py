"""Load test: researchers asking questions and browsing history, against the full stack
(API, SAQ queue, worker, agent graph, Postgres) with the mock LLM.

    cd infra
    docker compose exec db createdb -U apda apda_load        # once
    LLM_MOCK_LATENCY_MS=1000 docker compose -f docker-compose.yml \\
        -f docker-compose.loadtest.yml up -d --build backend worker
    cd ../backend
    uv run locust -f tests/performance/locustfile.py --host http://localhost:8000 \\
        --headless -u 20 -r 5 -t 90s

"Run: submit -> done" is the time a user waits for an answer: submit, then poll until
the run finishes. It's reported alongside the HTTP requests.
"""

import random
import time

from locust import HttpUser, between, task

QUESTIONS = [
    "How did retrenchment of residents and non-residents change since 2015?",
    "Which university had the highest graduate employment rate in 2023?",
    "How did the share of women working 60+ hours change from 2023 to 2025?",
    "Which MRT stations have the shortest travel time to junior colleges?",
]
POLL_SECONDS = 0.5
RUN_TIMEOUT_SECONDS = 180  # matches QUERY_JOB_TIMEOUT_SECONDS


class Researcher(HttpUser):
    wait_time = between(1, 3)

    @task(3)
    def ask(self) -> None:
        started = time.perf_counter()
        with self.client.post(
            "/api/queries", json={"query": random.choice(QUESTIONS)}, catch_response=True
        ) as response:
            if response.status_code != 202:
                response.failure(f"expected 202, got {response.status_code}")
                return
            run_id = response.json()["run_id"]

        status = "running"
        while status == "running" and time.perf_counter() - started < RUN_TIMEOUT_SECONDS:
            time.sleep(POLL_SECONDS)
            poll = self.client.get(f"/api/queries/{run_id}", name="/api/queries/[run_id]")
            status = poll.json().get("status", "running") if poll.ok else "running"

        self.environment.events.request.fire(
            request_type="RUN",
            name="submit -> done",
            response_time=(time.perf_counter() - started) * 1000,
            response_length=0,
            exception=None if status == "completed" else RuntimeError(f"run ended {status}"),
            context={},
        )

    @task(1)
    def browse_history(self) -> None:
        self.client.get("/api/analyses")
