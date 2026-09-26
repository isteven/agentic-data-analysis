# Architecture -- Agentic Policy Data Analytics Platform

> **Living document.** Every section states what is **built** today and what is **planned**. Status as of 2026-09-25: milestone M1 complete, M2 in progress. Async worker wired; live trace served over SSE; frontend still polls.

## 1. Overview

A full-stack agentic system: a policy researcher asks a question in plain English; a multi-agent pipeline picks the relevant government datasets, computes the statistics, writes a cited report and checks every number in it; the agents' reasoning steps are shown in the UI.

**Target shape:**

```
+-------------+  POST /api/queries (202 + run_id)  +-------------+
|  Frontend   | ---------------------------------> |   Backend   |
|  (Next.js)  | <------ SSE: live agent trace ---- |  (FastAPI)  |
+-------------+                                    +------+------+
                                                          | enqueue
                                                          v
                          +---------------+        +------+------+
                          |     Redis     | <----> |   Worker    |
                          | queue+streams |        | (SAQ, runs  |
                          +---------------+        |  LangGraph) |
                                                   +------+------+
                                                          | persists
                                                          v
                                                   +-------------+
                                                   | PostgreSQL  |
                                                   +-------------+

Worker also calls: LLM providers (via one provider factory),
data.gov.sg Datastore API (client built, no dataset uses it now), local dataset files (backend/data/incoming/).
```

**Today:** `POST /api/queries` creates the run (status `running`) and enqueues it on the SAQ worker, returning `202` immediately; `GET /api/queries/{run_id}` polls for the result. The worker appends each trace event to a Redis Stream the moment it is emitted, and `GET /api/agent-trace/{run_id}` relays it to the browser as SSE. The frontend doesn't consume the stream yet.

**Why this shape:** the API process only does fast work (accept a query, serve history, relay the trace stream); the slow work (several LLM calls, data loading) runs in a separate worker, so the API stays responsive and the trace can stream across processes.

## 2. Status by layer

| Layer | Target | Built today | Status |
|---|---|---|---|
| Frontend | Next.js + TypeScript, Recharts, TanStack Query | Next.js + TypeScript: one query page with report, chart, data table and agent-trace panel | Partial |
| Backend API | FastAPI: 202 + background run, SSE, history, export | FastAPI: `POST /api/queries` (202 + worker run), `GET /api/queries/{run_id}` (poll), health routes | Partial |
| Agent pipeline | LangGraph with loops (SQL retry, quality review) -- section 3.2 | LangGraph, 6 nodes; ReAct SQL planner with gate-checked retries; reviewer loop back to planner / report writer | Partial |
| Async / queue | SAQ worker on Redis | `run_query_task` built, publishes trace events, and runs every query (`POST /api/queries` enqueues it); `worker` service in Compose | Built |
| Real-time trace | Redis -> SSE | Worker writes each event to a Redis Stream as emitted; `GET /api/agent-trace/{run_id}` serves it as SSE; frontend not wired yet | Partial |
| LLM providers | OpenAI + AWS Bedrock, automatic fallback | OpenAI + Bedrock (Claude via `global.` inference profiles) via one factory; UI picker; automatic per-call fallback, traced. Verified live both ways (Bedrock only; OpenAI key broken -> Bedrock) | Built |
| Data sources | data.gov.sg + MOM; CSV, Excel, live API | CSV + Excel from both sources; API client with file fallback built but unused since the dataset swap | Partial |
| Database | PostgreSQL | PostgreSQL, 7 tables + generated `data` views, Alembic migrations | Built |
| Visualisations | Charts driven by backend chart specs | Every answer with a number is charted. Code picks the type from the result's shape (time axis with 3+ periods: line; 2 periods, categories or one value: bar; >30 categories: the 15 at the end the question is about); the planner only suggests columns (`app/agents/chart.py`). Time-range questions are answered one row per period. Recharts; long labels as horizontal bars | Built |
| History / export | History page; PDF / JSON / CSV export | `/history` list + detail page; chart export to PDF, table export to CSV (client-side); no JSON export | Partial |
| Cost tracking | Tokens per LLM call and per run | Provider-reported tokens per call (`llm_calls`), per-model run totals, returned by the API, shown in a Token usage tab; no dollar estimate (by choice) | Built |
| Testing | Unit, integration, LLM accuracy / consistency, data quality, load | 62 unit tests | Partial |
| CI/CD | GitHub Actions | None | Planned |
| Deployment | Docker Compose (5 services) + one-time validated AWS deploy | Docker Compose, 4 services (no worker yet) | Partial |

## 3. Agent design

### 3.1 Current pipeline (built)

```
START -> intent -> coordinator -> extraction -> analytics (ReAct SQL planner) -> report_writer -> validator -> reviewer -> END
                                          ^  describe / sample / run_sql  |
                                          +------ observe, retry ---------+
```

| Node | LLM? | What it does |
|---|---|---|
| **intent** | Yes (quality tier) | Restates the question as one precise reading (a share names its denominator; relative time becomes concrete years), declines what no dataset covers, and returns `time_range` ({start, end}) when the question spans periods, read from its meaning, not keywords (`app/agents/nodes/intent.py`) |
| **coordinator** | Yes (fast tier) | Reads the dataset catalog (`manifest.yaml`) and picks the datasets relevant to the question (structured output) |
| **extraction** | No | Checks each chosen dataset is stored, maps it to its typed view, and traces the data-quality facts inferred at ingest (totals/overlaps excluded, unverified periods, summable measures) |
| **analytics** | Yes (quality tier; fast-tier plans ran out of steps on multi-step questions) | ReAct planner (`app/agents/planner.py`): tools `describe_view`, `sample_rows`, `run_sql`, then `submit_answer(sql, interpretation)` or `cannot_answer`. Max 8 tool calls. Every query goes through the SQL gate and read-only runner; a rejection is an observation the planner fixes. The submitted query's result becomes `Finding`s |
| **report_writer** | Yes (quality tier) | Writes the report from the query result and findings only, stating how the question was interpreted and citing sources |
| **validator** | No | Every number in the report must match a finding (1% tolerance); numbers from the question or result labels (cells or column names) count as context. Appends a warning otherwise |
| **reviewer** | Yes (quality tier) | LLM judge of meaning, not arithmetic: sees the question, what each queried column means, the SQL, result and report. `pass`, `wrong_analysis` (back to analytics) or `poor_report` (back to report_writer), with the reason as feedback. Max 1 re-route; after that the answer keeps a visible caveat |

**Safety of LLM-written SQL** (`app/data/sql_gate.py`, `sql_runner.py`): sqlglot allows one `SELECT` over `data` views only, known columns (with "did you mean" hints), no `SUM` over non-additive measures, no side-effect functions, and runs the SQL regenerated from the checked tree. Postgres then runs it in a `READ ONLY` transaction as the `NOLOGIN` role `data_reader` (SELECT on the views only), with a 5 s timeout and a 500-row cap. Each layer alone stops a write.

**Why the reviewer:** the validator proves the report matches the result, not that the result answers the question. Example caught live: "Which gender works longer?" was answered by averaging (then summing) a head-count column; the reviewer sent it back and the re-plan compared each sex across hours bands.

**Still open** (from 3.2): intent rewriting; `wrong_datasets` routing back to the coordinator; units carried into findings.

### 3.2 Planned additions

| Step | LLM? | Responsibility |
|---|---|---|
| Intent | Yes | Rewrite the question precisely ("layoff" -> retrenchment, "past 3 years" -> 2023-2025); reject questions the catalog can't answer |
| Quality review | Yes | **Built** (planner + report writer routes, section 3.1); routing back to the coordinator for wrong datasets is not |

**Principles:**
- LLMs interpret the question, choose what to compute and judge the result; **the database computes every number**. No LLM ever re-types data.
- **Data rules live in the views, not the prompt:** views expose only rows that are safe to add up. A spike showed prompt instructions alone did not stop double-counting; view shape did. The rules are inferred from the data (section 5.5), not written per dataset.
- Column knowledge comes from the profile made at ingest, so the query path has no hardcoded column names or operation lists.

### 3.3 Shared state

One `AgentState` (`backend/app/agents/state.py`), shared by all nodes: `query`, `run_id`, `plan`, `raw_extracts` (row counts, columns, source mode), `findings`, `report_markdown`, `grounded`, `trace_events`, `errors`. Dataframes are kept outside the state in a per-run store keyed by `run_id`, so the state stays JSON-serialisable.

### 3.4 Agent trace (ReAct visibility)

Every node calls `emit_trace(state, node, step_type, content)` with `step_type` in `reasoning | action | observation`.

- **Built:** trace events are persisted to `agent_traces` at the end of the run. During the run, the worker installs a trace sink (a context var read by `emit_trace`), so each event -- including every planner tool call -- is appended to the Redis Stream `agent-trace:{run_id}` as it happens, not once per node.
- **Built:** `GET /api/agent-trace/{run_id}` (SSE): `trace` events, then `done` with the run status. Reads the stream from the start, so a late subscriber misses nothing; the stream expires 1 h after the run, after which the route replays from `agent_traces`. Gives up after 10 min if a crashed worker never writes `done`.
- **Why a Stream, not pub/sub:** pub/sub keeps nothing, and the first events fire before the browser can subscribe, so they'd be lost.
- **Built:** `POST /api/queries` enqueues `run_query_task` and returns `202` + `run_id`; `GET /api/queries/{run_id}` polls `analysis_runs` + `agent_traces` for the result (this is the "fallback if the stream drops" path once SSE exists, and the only path today).
- **Planned:** the frontend consumes the SSE stream (steps appear live), polling `GET /api/queries/{run_id}` as the fallback.

### 3.5 Failure handling

- **Built:** each dataset loads in its own try/except, so one failure doesn't stop the others; a failed live API call falls back to the cached file and is tagged `file_fallback` in the trace; any graph exception ends the run with status `failed`, and a partial result is still saved; no matching dataset gives status `partial` with an honest explanation.
- **Built:** gate-rejected or failing SQL is returned to the planner as an observation; the planner can decline (`cannot_answer`) and the run ends `partial` with the reason.
- **Built:** automatic LLM provider fallback, per call (4.2).
- **Built:** quality review sends a wrong analysis or a poor report back to the step that caused it, once; a second failure keeps the answer with a caveat.

## 4. LLM providers

### 4.1 Provider factory

All agent code gets a model from `get_chat_model(provider, model_tier)` in `backend/app/llm/provider_factory.py`; nothing imports a provider SDK directly. Two independent choices:

- **Provider:** `openai` and `bedrock` (`langchain_aws.ChatBedrockConverse`) built; `azure_openai` / `vertex_ai` stubs.
- **Tier:** fixed per node, mapped to model ids in `.env`: `fast` for the coordinator (picking datasets); `quality` for intent, analytics (the SQL planner), report writer and reviewer. Nothing switches tier during a run.

### 4.2 Switching and fallback

- **Built -- per-request choice:** `POST /api/queries` takes an optional `provider`; otherwise `LLM_DEFAULT_PROVIDER`. Nodes get their model via `node_model(state, node, tier)` (`app/agents/llm.py`).
- **Built -- automatic fallback:** `get_chat_model()` returns a `FallbackChatModel` holding the chosen provider, then `LLM_FALLBACK_PROVIDER`. Any error on a call (auth, outage, rate limit after the SDK's own retries, malformed structured output) retries that call on the next provider. The switch is a trace event ("LLM provider openai failed (AuthenticationError); retried on bedrock") and is stored in `analysis_runs.provider_used` (e.g. `openai->bedrock`). A provider that isn't configured is skipped, so either one alone still works.
- **Why not LangChain `.with_fallbacks()`:** it doesn't report which provider answered, so the switch couldn't be traced. The wrapper mirrors `bind_tools` / `with_structured_output` / `ainvoke`, so node code is unchanged.
- **Built:** a provider picker in the chat box.
- **Planned:** skip a provider for the rest of a run after an auth/access error, instead of retrying it on every call.
- **Setup note:** each Anthropic model needs a one-time AWS Marketplace subscription per account (done from the Bedrock Playground by an admin); the app's IAM user only needs `bedrock:InvokeModel`.

## 5. Data layer

### 5.1 Datasets

| Dataset | Source | Format | Coverage |
|---|---|---|---|
| `retrenchment_by_residential_status` | data.gov.sg | CSV | 2007-2025 |
| `mrt_to_junior_college_travel` | data.gov.sg | CSV | no time dimension (189 stations x 18 colleges) |
| `graduate_employment_survey` | data.gov.sg | CSV | 2013-2024 |
| `mom_usual_hours_by_occupation_{2023,2024,2025}` | MOM | Excel (sheet F2) | one file per year, one combined view |

The files are curated mock data derived from public downloads. Details and known data issues: `DATA_SOURCES.md`.

### 5.2 Manifest

`backend/data/manifest.yaml` catalogs every dataset with **metadata only**: `id`, `source`, `title`, `topic`, `mode` (`file` | `api`), `file_path`, `format`, `sheet_name`, `resource_id`, `api_fallback`, `group` (files that form one view), `year` (for files with no year column). The coordinator reads it to choose datasets.

`column_meta` is optional and holds only units and descriptions; there are no per-dataset data rules.

**Source mode is a property of the dataset, not a per-query switch.** `api` mode is only for pre-vetted data.gov.sg `resource_id`s.

### 5.3 Loading and cleaning

- **Parsers:** `csv_parser.py` (pandas; digit strings with a leading zero stay text, e.g. postal codes); `excel_parser.py` (openpyxl, built for the MOM F2 layout); `api_client.py` (data.gov.sg Datastore Search, pagination, 2 attempts with timeout).
- **Missing values:** `-`, `na`, `N.A.` and similar become missing, never 0.
- **Cleaning at ingest** (`app/data/cleaning.py`): adds `year` from the manifest where a file has none.

### 5.4 Seeding and typed views

On startup the backend runs Alembic migrations, then `scripts/seed_datasets.py`:

1. **Prune:** datasets no longer in the manifest lose their stored rows; their catalog row is deleted unless a past analysis cites it.
2. **Seed:** each file is parsed, profiled (section 5.5) and written to `dataset_records` (one JSONB document per row), with a `datasets` catalog row. Skipped when the file hash and `PROFILER_VERSION` are unchanged.
3. **Views:** the `data` schema is dropped and rebuilt: one typed view per dataset (real `integer` / `double precision` / `text` columns), files sharing a `group` combined with `UNION ALL`, plus a `<view>_totals` view (additive measures summed per period) where there is something to sum.

Views are derived, so rebuilding them loses nothing. One generic table avoids a table per CSV. Reading through a JSON view is 2-7x slower than a typed table (about 1 ms at current sizes); materialized views close the gap past ~100k rows.

**Known issue:** the stored file path is absolute and isn't rewritten when only the environment changes (Docker vs. host).

### 5.5 Data quality and structure inference

The profiler records per column: role (time / dimension / measure), range, nulls, distinct values. `app/data/structure.py` then infers, **from the numbers only**:

- **Hierarchy:** a value equal to the sum of other values in every cell (within 3 rounding units, at least 5 cells) is their parent. Views keep the lowest level and add `<column>_level_N` parent columns, so any level is a `GROUP BY`.
- **Grand totals and overlaps:** a parent that is at least every other value everywhere is a grand total and is excluded; values outside its breakdown overlap it (MOM `More Than 48 Hours`).
- **Parallel classification schemes:** two separate groups of values with equal sums; the one covering fewer cells is dropped.
- **Classification eras:** a new era starts when a column's values change; an era whose relations don't form a clean tree (a value with two parents, cycles) is marked unverified and left out of the views.
- **Additivity:** a measure is additive only if some column proves it; rates, means and medians default to non-additive, the safe side for `SUM`.

Validated on the earlier industry datasets (full 3-level industry tree recovered; pre-2006 eras rejected) and on MOM (views sum to the published totals within rounding). **Not yet handled:** totals stored as separate columns (e.g. `retrench_total` beside its parts); a data-quality panel in the UI.

## 6. Database

PostgreSQL only, SQLAlchemy async ORM, Alembic migrations. All primary keys are Postgres `UUID`.

| Table | Purpose | In use? |
|---|---|---|
| `datasets` | Catalog row per dataset: source, mode, file path, content hash, `quality_report` (incl. profiler version) and `schema_profile` (JSON, incl. inferred structure) | Yes |
| `dataset_records` | Every cleaned source row as a JSONB document; read through the generated views in the `data` schema | Written by seeding; read by the SQL planner through the views |
| `analysis_runs` | One per query: text, status, provider, report, `token_usage` (per-model totals) | Yes; `session_id`, `query_hash`, `estimated_cost_usd` columns reserved for planned features |
| `analysis_run_datasets` | Which datasets a run used | Yes |
| `agent_traces` | Persisted trace events | Yes |
| `llm_calls` | One row per LLM attempt: node, tier, provider, model, input / output / cached input tokens, latency, outcome | Yes |
| `findings` | Computed values with dataset and field reference | Yes |
| `sessions` | Chat sessions | Reserved (planned chat UI) |

## 7. Backend API

| Endpoint | Status | Purpose |
|---|---|---|
| `POST /api/queries` | Built (synchronous) -> planned: returns `202` + `run_id` | Submit a question |
| `GET /api/health`, `GET /api/health/providers` | Built | Liveness; which providers are configured |
| `GET /api/queries/{run_id}` | Built | Poll result (fallback if the stream drops); includes `token_usage` (per-model totals + each call) once the run finishes |
| `GET /api/agent-trace/{run_id}` | Built | Live trace via SSE |
| `GET /api/analyses` | Built | History list (query, status, provider, timestamps); detail reuses `GET /api/queries/{run_id}` |
| `GET /api/datasets` | Planned | Dataset catalog |

**Async processing:** SAQ worker (`backend/app/worker.py`), same Docker image as the API with a different command (`worker` service in `infra/docker-compose.yml`); `scripts/queue_status.py` inspects the queue.

## 8. Frontend

- **Built:** a chat-style query interface (`frontend/app/page.tsx`) with a provider picker; each answer has up to four tabs: Report (chart from `components/ResultChart.tsx`, Recharts, above the report text), Data (query result table, `components/ResultTable.tsx`), Agent steps (`components/AgentTrace.tsx`) and Token usage (`components/TokenUsage.tsx`: totals per model and each LLM call, as the provider reported them; shown once a run has usage). Agent steps stream live over SSE while a run is in progress (`lib/runs.ts`), falling back to polling `GET /api/queries/{run_id}` if the stream drops. `/history` lists past runs; `/history/{runId}` shows the full result. Report tab has Export PNG / PDF for the chart (SVG rasterized; PDF via `jspdf`); Data tab has Export CSV (client-side, no backend export endpoint).
- **Planned:** citations panel; data-quality panel; JSON export; follow-up questions using earlier turns as context (needs the session-id backend work in `project-management.md`'s M2.3, not yet done).
- **State:** TanStack Query for server data; no global state library (no need for one at this size).

## 9. Non-functional requirements

### 9.1 Performance

**Targets:** first trace event on screen within 2 s of submitting; a simple single-dataset query completes within 60 s.

**Fixed now that the worker is wired:** the run row is created at submit time with status `running` (`create_run()`), so a poll or the history page can find it immediately.

**Still open:**

- pandas and openpyxl run on the async event loop inside the worker, so one run's computation stalls the others in the same process (SAQ concurrency 4) -> move to a thread.
- One database session is held for the whole run, including LLM calls -> use short-lived sessions.
- Live API datasets are fetched in full on every query -> cache them (no dataset uses the API right now).
- **Measured** (Locust, mocked LLM, TESTING.md): the stack adds under 0.5 s per run; the limit is worker capacity (one worker runs 4 jobs at once, ~0.7 runs/s at ~5 s of LLM time per run), and throughput scales almost linearly with `--scale worker=N` (3 workers: 2.9x). With real LLMs, provider rate limits come first.

### 9.1a Observability

- **Built:** structured logs as the integration point. `LOG_FORMAT=json` makes every line (API, worker, Uvicorn) one JSON object; lines logged during a run carry its `run_id` (a context variable bound by the worker). Events with fields: `http request` (middleware, `app/api/middleware.py`), `llm call` (tokens, model, latency, outcome), `agent step`, `run finished` (status, duration, calls, fallbacks). Per-run detail also lives in `agent_traces` and `llm_calls`.
- **Not built, by choice:** a metrics/tracing stack (Prometheus + Grafana, OpenTelemetry, LangSmith, alerting). The logs feed any of them directly; LangSmith needs only environment variables. See the Innovation Assessment for the production setup.

### 9.2 Cost

- **Built:** model tiering (fast / quality); prompts contain findings, never raw data.
- **Built -- token usage:** `FallbackChatModel` attaches a LangChain callback to every attempt and records the token counts the provider reports (`usage_metadata`: input, output, cached input), the model that answered, latency and outcome (`app/llm/usage.py`). `node_model()` tags each call with its node and tier; rows go to `llm_calls`, per-model totals to `analysis_runs.token_usage`. Counts are the provider's own, not estimated. Totals are per model only: models tokenize differently, so a fallback run has one entry per model and no grand total. A failed attempt that got no answer has zero tokens; one that answered but failed parsing keeps its billed tokens.
- **Why tokens, not dollars:** a dollar figure needs a hand-maintained price table and would still be an estimate; tokens are exact.
- **Planned:** response cache for repeat questions; `max_tokens` cap per step; cache for live API data.

### 9.3 Security and privacy

- **Built:** request validation (Pydantic: question 1-2,000 characters; only `openai` / `bedrock` can be chosen, never `mock` or unbuilt stubs); **rate limiting** on `POST /api/queries` (`RATE_LIMIT_QUERIES_PER_MINUTE` per client IP, default 10, Redis fixed window, 429 with `Retry-After`; fails open if Redis is down; `app/api/rate_limit.py`); CORS restricted to the frontend origin; secrets only in per-service `.env` files (never committed); `pydantic-settings` validates config at startup.
- **Planned:** CI dependency scanning; prompt-injection mitigation for text coming from data files (the planned fixed plan vocabulary limits what injected text could do).
- **Privacy:** all datasets are public, aggregate statistics; no personal data flows through the system.

## 10. Deployment

- **Built:** `infra/docker-compose.yml` runs `db` (postgres:16), `redis` (redis:7), `backend` and `frontend`; startup migrates and seeds automatically. Each service has its own `.env` (copy from `.env.example`); there is no root `.env`.
- **Planned:** a `worker` service (same backend image); a one-time AWS deployment (ECS/Fargate, RDS, ElastiCache, Secrets Manager) to validate the deployment docs, then torn down; the grader's path stays local Docker Compose.

## 11. Milestones

| Milestone | Scope | Status |
|---|---|---|
| M1 | Walking skeleton: seeded data, one LLM call, minimal UI, Docker Compose | Done |
| M2 | Agentic core: real pipeline, live API, worker + SSE, Bedrock + fallback, dashboard, history, cost tracking | In progress |
| M3 | Tests (incl. LLM accuracy and load), CI, docs (README, TESTING) | Not started |
| M3.5 | One-time AWS deployment validation | Not started |
| M4 | Polish, bonus items, Innovation Assessment, demo rehearsal | Not started |

## 12. Key decisions

| Decision | Choice | Why |
|---|---|---|
| Agent framework | LangGraph | The planned retry and review loops need conditional edges; state is inspectable at every step |
| Agent count | 5 now (3 required + report writer + validator), growing with the redesign | "What the data says" and "how to explain it" fail differently; the validator is the hallucination check |
| Who computes numbers | The database (LLM-written SQL, checked before running), never an LLM | Every number stays verifiable |
| Query language | Checked SQL over generated views, not a custom plan vocabulary | A custom vocabulary is our own capability list to maintain; SQL is standard and LLMs are fluent in it. Checks + view shape keep it safe (spike: valid SQL 12-14/14 first try) |
| Task queue | SAQ (Redis) | Async-native; Celery is too heavy; arq is in maintenance mode |
| Real-time transport | SSE | The trace only flows server -> client; plain HTTP with built-in browser reconnect. The brief mentions WebSocket; SSE serves the same purpose |
| Database | PostgreSQL only | Unit tests mock the database; integration tests use real Postgres, so a second engine adds nothing |
| Dataset rows | One generic JSONB table + typed views generated per dataset | SQL generation needs real columns; one fixed table avoids per-CSV table maintenance; views are rebuildable |
| Data rules (totals, hierarchies, additivity) | Inferred from the numbers at ingest, not declared per dataset | New files work without code or manifest rules; inference needs a tolerance, minimum evidence and a clean tree, and uncertain eras are excluded rather than guessed |
| Source mode | Per dataset, in the manifest | Reliability differs by dataset, not by question; live API only for pre-vetted tables, with file fallback |
| LLM providers | OpenAI + AWS Bedrock | Bedrock is a real cloud platform, a literal answer to "multi-cloud" |
| Provider switching vs. fallback | Both, separately | The brief asks for both |
| Frontend state | TanStack Query, no global store | Nothing needs one at this size |
| Hosting | Local Docker Compose + one-time validated AWS deploy | Hosting isn't required; the docs still get tested against a real deployment |

## 13. Future work

- SingStat live integration; any free-text dataset discovery.
- Provider-native prompt caching; semantic (embedding-based) matching of repeat questions.
- Vector database / RAG over past analyses.
- Streaming the report text token by token.
- Production concerns (for the Innovation Assessment): SSO/RBAC, audit logging, network isolation, data classification.
