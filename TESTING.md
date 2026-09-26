# Testing

Results below are from 2026-09-26.

| Layer | What it checks | Tests | Runs in | Result |
|---|---|---|---|---|
| Unit | Chart rules, SQL gate, planner loop, profiler, structure inference, views, token usage, provider fallback, mock LLM, run reliability (worker save/close, step error boundary), logging, rate limit and request validation | 148 | CI, every push | pass |
| Integration | The full agent graph on real Postgres with a scripted LLM; persistence; data accuracy against published figures; trace order; startup logging | 27 | CI (Postgres service) | pass |
| LLM evals | The real pipeline and model: accuracy, consistency, no hallucination | 8 questions × 3 runs | Manual workflow (costs API calls) | 24/24 |
| Load | The full stack under concurrent users, LLM mocked | Locust, 3 scenarios | Manual | 0 failures; see below |
| Frontend | Chart data rules (sort/cut, grouping, lone number), tab visibility, token usage view, CSV content, following a run (cancel, silent stream, deadline), New Chat mid-run, app shell, refused-submit messages (Vitest + Testing Library); lint, typecheck, build | 27 | CI, every push | pass |

**Coverage:** 82% of backend lines (unit + integration); agent pipeline modules 89–100% (planner 92%, SQL gate 97%, reviewer 100%). CI uploads the unit coverage report.

How to run each layer: [README.md](README.md#tests).

## Hallucination detection

The design removes the main source first: **the LLM never produces a number**. It writes SQL; Postgres computes; the report may only cite the result. Then each layer catches a different failure:

| Layer | Catches | How |
|---|---|---|
| SQL gate (`app/data/sql_gate.py`) | Invented columns or views, unsafe SQL, summing a rate | `sqlglot` checks one `SELECT` over known views and columns ("did you mean" hints); no `SUM` on non-additive measures. Rejections go back to the planner to fix |
| Read-only execution (`sql_runner.py`) | Anything that slips past the gate | `READ ONLY` transaction as a `NOLOGIN` role with `SELECT` on views only; 5 s timeout; 500-row cap |
| Validator (`nodes/validator.py`, code) | A number in the report the database never produced | Every number must match a result value (1% tolerance); numbers from the question or result labels count as context. Otherwise the report carries a visible warning |
| Reviewer (`nodes/reviewer.py`, LLM judge) | Right numbers answering the wrong question (missing filter, wrong level, wrong measure) | Judges the SQL against the agreed reading of the question; sends the run back once to the step at fault, then keeps a visible caveat |
| Intent (`nodes/intent.py`) | Answering a nearby question instead of declining | Declines when no dataset covers the subject |

The validator checks the report against the result, not the result against the truth: a correct-looking but wrong query passes it. That is what the reviewer and the evals are for.

## LLM evals

`tests/integration/test_llm_evals.py`, workflow `llm-evals.yml`. Each question runs 3 times on the real pipeline; every run must be:

- **accurate:** the expected value is in the query result. Expected values are MOM's published figures or computed by SQL straight from the views, never by the model;
- **consistent:** the same answer on every run;
- **grounded:** no unverified number in the report; an unanswerable question is declined.

| Case | Question (short) | Expected | Result |
|---|---|---|---|
| residents_2020 | Residents retrenched in 2020 | 14,380 (MOM published) | 3/3 |
| total_2009 | Total retrenchments in 2009 | 23,430 (MOM published) | 3/3 |
| hours_60_plus_2025 | Employed residents working 60+ hours, 2025 | SQL | 3/3 |
| women_60_plus_share | Share of women working 60+ hours, 2023→2025 | 3.29% in 2025 (SQL) | 3/3 |
| station_count | MRT/LRT stations in the travel data | SQL | 3/3 |
| top_university_2023 | Highest average employment rate across degrees | SQL | 3/3 |
| top_university_natural | "Which university had the highest graduate employment rate in 2023?" | SMU (SQL) | 3/3 |
| gdp_unanswerable | Singapore's GDP growth in 2020 | declined | 3/3 |

The evals drove real fixes: the planner moved to the quality tier (the 60+ hours share failed on the fast model), group questions are now answered per group (the university case was 0/3), and the intent step stopped declining computable counts (the 60+ hours count was 0/3).

## Reviewer checks

The reviewer was tested on its own with fixed answers, 3 judgements per case:

| Case | Expected | Result |
|---|---|---|
| Share of women computed over all workers (no sex filter) | sent back | 3/3 (fast model: 0/3) |
| "Which university…" answered by MAX per university | sent back | 3/3 |
| "Which university…" answered by the top degree row | sent back | 3/3 |
| Correct answer (average across degrees) | pass | 3/3 |
| "Which degree…" answered by a single row (control) | pass | 3/3 |

## Load and performance

`backend/tests/performance/locustfile.py`. A load test on the real LLMs would mostly measure their rate limits, so the LLM is replaced by a **mock provider** (`app/llm/mock.py`) that returns deterministic, valid answers after a set delay. Everything else runs for real: API, SAQ queue, worker, agent graph, SQL gate, Postgres, persistence. `infra/docker-compose.loadtest.yml` switches to the mock and a separate `apda_load` database.

Each simulated user asks a question and polls until it's done (**submit → done**, the wait a user sees), and browses history. 90 s runs (60 s for A), local Docker:

| Scenario | Users | LLM delay | Workers | Runs done | Submit → done (median / p95) | API submit / poll (median) | Failures |
|---|---|---|---|---|---|---|---|
| A: infrastructure only | 10 | 0 | 1 | 183 in 60 s | 0.56 s / 0.58 s | 49 ms / 5 ms | 0 |
| B: realistic LLM time | 20 | 1 s per call (~5 s per run) | 1 | 68 | 23 s / 24 s | 55 ms / 8 ms | 0 |
| C: B with 3 workers | 20 | 1 s per call | 3 | 196 | 5.7 s / 7.2 s | 49 ms / 5 ms | 0 |

- The stack itself adds **under 0.5 s** per run (A: every run was done at the first 0.5 s poll).
- The limit is **worker capacity**, not the API: one worker runs 4 jobs at once, about 0.7 runs/s at ~5.5 s each (B measured 0.77/s), so runs queue. Throughput scales almost linearly with workers (3 workers: 2.9×, waits back to a run's own time). Scale with `docker compose up --scale worker=N`.
- The API stayed fast throughout (polling at 34 requests/s, p95 14 ms).

With real LLMs, provider rate limits come first: gpt-4o allows about 30k tokens/min on the tested account, roughly 12 calls a minute at ~2.5k tokens each.

## Data quality

`tests/integration/test_data_accuracy.py` checks the loaded data, not the agents:

- MOM hours views sum to MOM's published grand totals for 2023–2025, with no `Total` or overlapping rows exposed (double counting once reported 70,880 retrenchments for 2020 instead of 26,110);
- 2020 retrenchments match MOM's Labour Market Report (26,110; 14,380 residents), and each year's parts add up to its total;
- employment rates are percentages; suppressed cells (`-`) are missing, never 0;
- every manifest dataset is loaded; planner SQL cannot write, even past the gate.

## Not covered

- **Frontend end to end:** unit and component tests only (jsdom); no browser-level tests. Page flows were checked in a headless browser during development.
- **Bedrock:** the evals ran on OpenAI; Bedrock was verified live but not through the eval suite.
- **Relative time** ("the last five years") is resolved by the model and can vary between runs.
