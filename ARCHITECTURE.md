# Architecture -- Agentic Policy Data Analytics Platform

> **Living document.** Every section states what is **built** today and what is **planned**. Status as of 2026-09-24: milestone M1 complete, M2 in progress.

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
                          | queue + pubsub|        | (SAQ, runs  |
                          +---------------+        |  LangGraph) |
                                                   +------+------+
                                                          | persists
                                                          v
                                                   +-------------+
                                                   | PostgreSQL  |
                                                   +-------------+

Worker also calls: LLM providers (via one provider factory),
data.gov.sg Datastore API, local dataset files (backend/data/incoming/).
```

**Today:** the backend runs the whole pipeline synchronously inside `POST /api/queries` and returns the full report and trace in one response. The worker task exists but nothing enqueues it yet, and there is no SSE route.

**Why this shape:** the API process only does fast work (accept a query, serve history, relay the trace stream); the slow work (several LLM calls, data loading) runs in a separate worker, so the API stays responsive and the trace can stream across processes.

## 2. Status by layer

| Layer | Target | Built today | Status |
|---|---|---|---|
| Frontend | Next.js + TypeScript, Recharts, TanStack Query | Next.js + TypeScript: one query page plus an agent-trace panel | Partial |
| Backend API | FastAPI: 202 + background run, SSE, history, export | FastAPI: synchronous `POST /api/queries`, health routes | Partial |
| Agent pipeline | LangGraph with loops (plan retry, quality review) -- section 3.2 | LangGraph, 5 nodes in a straight line | Partial |
| Async / queue | SAQ worker on Redis | `run_query_task` built and publishes trace events; not wired to any route | Partial |
| Real-time trace | Redis pub/sub -> SSE | Trace returned once, after the run | Partial |
| LLM providers | OpenAI + AWS Bedrock, automatic fallback | OpenAI only; Bedrock stubbed | Partial |
| Data sources | data.gov.sg + MOM; CSV, Excel, live API | All built; live API with file fallback verified both ways | Built |
| Database | PostgreSQL | PostgreSQL, 6 tables, Alembic migrations | Built |
| Visualisations | Charts driven by backend chart specs | None | Planned |
| History / export | History page; PDF / JSON / CSV export | None | Planned |
| Cost tracking | Tokens and estimated cost per run | None | Planned |
| Testing | Unit, integration, LLM accuracy / consistency, data quality, load | 11 unit tests | Partial |
| CI/CD | GitHub Actions | None | Planned |
| Deployment | Docker Compose (5 services) + one-time validated AWS deploy | Docker Compose, 4 services (no worker yet) | Partial |

## 3. Agent design

### 3.1 Current pipeline (built)

```
START -> coordinator -> extraction -> analytics -> report_writer -> validator -> END
```

| Node | LLM? | What it does |
|---|---|---|
| **coordinator** | Yes (fast tier) | Reads the dataset catalog (`manifest.yaml`) and picks the datasets relevant to the question (structured output) |
| **extraction** | No | Loads each selected dataset: live data.gov.sg API with file fallback, or the local file; applies the manifest's cleaning rules (section 5.3) |
| **analytics** | No | Matches query words to category values, keeps non-overlapping rows (`default_slice`), sums the measure per year plus a first-to-last change; emits `Finding`s |
| **report_writer** | Yes (quality tier) | Writes the report from the findings only, citing the source dataset for each number |
| **validator** | No | Extracts every number from the report and checks it matches a finding (1% tolerance); appends a warning if any don't |

**Known limitations** (addressed by 3.2):

- Straight line: no agent looks at a result and decides what to do next.
- Analytics relies on hardcoded metric-column names and only sums; question wording is matched literally (no year ranges, no synonyms).
- The validator checks the report against the findings, not the findings against the truth: a wrong computation passes as "grounded".
- Only two nodes make decisions.

### 3.2 Planned: query-planning redesign

```
intent -> coordinator -> planner -> plan check -> executor -> report_writer -> number check -> quality review -> END
 (LLM)      (LLM)         (LLM)   ^  (code)  |    (code)        (LLM)            (code)          (LLM)
                                  +- retry --+                                                   |
             ^            ^                                                                      |
             +------------+------------------------ route back by root cause -------------------+
```

| Step | LLM? | Responsibility |
|---|---|---|
| Intent | Yes | Rewrite the question precisely ("layoff" -> retrenchment, "past 3 years" -> 2023-2025); reject questions the catalog can't answer |
| Coordinator | Yes | Pick datasets |
| Planner | Yes | Turn the question into a structured query plan: filters, group-by, aggregations, derived values (ratio, growth, share, ...), top-N |
| Plan check | No | Reject plans naming columns, values or functions that don't exist; send the error back to the planner (max 2 retries) |
| Executor | No | Compute the plan in pandas; every result becomes a `Finding` |
| Report writer | Yes | Prose from findings only |
| Number check | No | Every number in the report must match a finding |
| Quality review | Yes | LLM judge: does the report answer the question, is anything misdescribed, were the right datasets used? Routes a failure back to the coordinator, planner or report writer |

**Principle:** LLMs interpret the question, choose what to compute and judge the result; **code computes every number**. An LLM never writes SQL or pandas code and never re-types data. Column knowledge comes from a schema profiled at ingest (section 5.5), so the query path has no hardcoded column names.

### 3.3 Shared state

One `AgentState` (`backend/app/agents/state.py`), shared by all nodes: `query`, `run_id`, `plan`, `raw_extracts` (row counts, columns, source mode), `findings`, `report_markdown`, `grounded`, `trace_events`, `errors`. Dataframes are kept outside the state in a per-run store keyed by `run_id`, so the state stays JSON-serialisable.

### 3.4 Agent trace (ReAct visibility)

Every node calls `emit_trace(state, node, step_type, content)` with `step_type` in `reasoning | action | observation`.

- **Built:** trace events are persisted to `agent_traces` and returned with the response; the UI shows them grouped by node. The worker task runs the graph with `.astream()` and publishes each new event to Redis channel `agent-trace:{run_id}`.
- **Planned:** `GET /api/agent-trace/{run_id}` relays that channel to the browser as SSE.

### 3.5 Failure handling

- **Built:** each dataset loads in its own try/except, so one failure doesn't stop the others; a failed live API call falls back to the cached file and is tagged `file_fallback` in the trace; any graph exception ends the run with status `failed`, and a partial result is still saved; no matching dataset gives status `partial` with an honest explanation.
- **Planned:** plan-check retries, quality-review routing (3.2), automatic LLM provider fallback (4.2).

## 4. LLM providers

### 4.1 Provider factory

All agent code gets a model from `get_chat_model(provider, model_tier)` in `backend/app/llm/provider_factory.py`; nothing imports a provider SDK directly. Two independent choices:

- **Provider:** `openai` (built), `bedrock` (planned, `langchain_aws.ChatBedrockConverse`), `azure_openai` / `vertex_ai` (stubs).
- **Tier:** `fast` (coordinator) or `quality` (report writer), mapped to model ids in `.env`.

### 4.2 Switching and fallback (planned)

- **User switching:** a provider picker in the query UI; resolution order is per-request choice -> environment default.
- **Automatic fallback:** on transient, auth or connection errors, retry on the other provider (LangChain `.with_fallbacks()`), recorded as a trace event ("OpenAI failed, retried on Bedrock").

## 5. Data layer

### 5.1 Datasets

| Dataset | Source | Format | Mode | Coverage |
|---|---|---|---|---|
| `retrenchment_by_industry` | data.gov.sg | CSV | file | 2006-2025 (pre-2006 excluded: classification change) |
| `job_vacancy_by_industry` | data.gov.sg | Live API (JSON) | api, file fallback | 1998-2025 |
| `graduate_employment_survey` | data.gov.sg | CSV | file | 2013-2024 |
| `mom_usual_hours_by_occupation_{2023,2024,2025}` | MOM | Excel (sheet F2) | file | one file per year |

Two government sources (data.gov.sg, MOM) and three formats (CSV, Excel, JSON API). SingStat is not used. Details and data-quality quirks: `DATA_SOURCES.md`.

### 5.2 Manifest

`backend/data/manifest.yaml` catalogs every dataset: `id`, `source`, `title`, `topic`, `mode` (`file` | `api`), `file_path`, `format`, `sheet_name`, `resource_id`, `api_fallback`, `column_meta`, plus per-source cleaning rules: `min_year`, `year`, `default_slice`. The coordinator reads it to choose datasets.

**Source mode is a property of the dataset, not a per-query switch.** `api` mode is only used for pre-vetted data.gov.sg `resource_id`s (fetch and paginate known tables; no free-text dataset search).

### 5.3 Loading and cleaning

- **Parsers:** `csv_parser.py` (pandas); `excel_parser.py` (openpyxl, built for the MOM F2 sheet layout: fixed header row, forward-filled `sex`, blank-row footer); `api_client.py` (data.gov.sg Datastore Search, pagination, 2 attempts with timeout).
- **Missing values:** `-`, `na`, `N.A.` and similar become missing, never 0.
- **Shared cleaning** (`app/data/cleaning.py`, used by both seeding and query-time loading; lands with PR `fix/double-counted-aggregates`):
  - `min_year` cut-off.
  - `year` taken from the manifest for files that have no year column.
  - `default_slice`: several sources mix totals, parent categories and their sub-categories, or two classification schemes, in one column (e.g. `manufacturing` alongside its sub-industry `electronic products`), so summing every row double-counts. When a query doesn't filter on such a column, only a non-overlapping set of rows is used.

### 5.4 Seeding

On startup, the backend's lifespan hook runs Alembic migrations, then `scripts/seed_datasets.py`. For each dataset with a local file, the seed step parses it and stores one `datasets` row: metadata, file path, content hash and a quality summary (row count, column count, nulls per column). Re-seeding is skipped when the file's content hash is unchanged.

**Dataset rows themselves are not stored in Postgres; files are read at query time.** At the current size (at most ~4,600 rows per dataset) parsing takes milliseconds, and benchmarking showed reading the whole file is faster than fetching the same rows from Postgres. Storing rows in Postgres pays off only once queries filter in SQL (benchmarked ~5x faster for a single-year filter). Revisit if datasets grow or filtering moves into SQL.

**Known issue:** the stored file path is absolute and isn't rewritten when only the environment changes (Docker vs. host), because the hash check skips re-seeding.

### 5.5 Data quality

- **Built:** missing-value handling, cleaning rules (5.3), null and row counts per dataset.
- **Planned:** a schema profiler at ingest (column roles; whether a measure can be summed; total rows; hierarchies; distinct values) feeding both the planner (3.2) and a data-quality panel in the UI.

## 6. Database

PostgreSQL only, SQLAlchemy async ORM, Alembic migrations. All primary keys are Postgres `UUID`.

| Table | Purpose | In use? |
|---|---|---|
| `datasets` | Catalog row per dataset: source, mode, file path, content hash, `quality_report` (JSON) | Yes |
| `analysis_runs` | One per query: text, status, provider, report | Yes; `session_id`, `query_hash`, `chart_specs`, `token_usage`, `estimated_cost_usd` columns reserved for planned features |
| `analysis_run_datasets` | Which datasets a run used | Yes |
| `agent_traces` | Persisted trace events | Yes |
| `findings` | Computed values with dataset and field reference | Yes |
| `sessions` | Chat sessions | Reserved (planned chat UI) |

## 7. Backend API

| Endpoint | Status | Purpose |
|---|---|---|
| `POST /api/queries` | Built (synchronous) -> planned: returns `202` + `run_id` | Submit a question |
| `GET /api/health`, `GET /api/health/providers` | Built | Liveness; which providers are configured |
| `GET /api/queries/{run_id}` | Planned | Poll result (fallback if the stream drops) |
| `GET /api/agent-trace/{run_id}` | Planned | Live trace via SSE |
| `GET /api/analyses`, `GET /api/analyses/{run_id}/export` | Planned | History; PDF / JSON / CSV export |
| `GET /api/datasets` | Planned | Dataset catalog |

**Async processing:** SAQ worker (`backend/app/worker.py`), same Docker image as the API with a different command; `scripts/queue_status.py` inspects the queue.

## 8. Frontend

- **Built:** a query form (`frontend/app/page.tsx`) showing the report and an agent-trace panel (`components/AgentTrace.tsx`) grouped by node and step type.
- **Planned:** charts (Recharts) driven by backend chart specs; citations panel; data-quality panel; provider picker; live trace via SSE with polling fallback; history page with export; chat-style interface with follow-up questions.
- **State:** TanStack Query for server data; no global state library (no need for one at this size).

## 9. Non-functional requirements

### 9.1 Performance

**Targets:** first trace event on screen within 2 s of submitting; a simple single-dataset query completes within 60 s.

**Known risks** (to fix when the worker is wired):

- pandas and openpyxl run on the async event loop, so one run's computation stalls the others -> move to a thread.
- One database session is held for the whole run, including LLM calls -> use short-lived sessions.
- The live vacancy API is fetched in full on every query, for data that changes yearly -> cache it.
- The run row is written only at the end -> create it at submit time with status `running`.
- Load tests will mostly hit LLM rate limits -> also test with a mocked LLM.

### 9.2 Cost

- **Built:** model tiering (fast / quality); prompts contain findings, never raw data.
- **Planned:** token and cost tracking per run at the provider factory; response cache for repeat questions; `max_tokens` cap per step; cache for live API data.

### 9.3 Security and privacy

- **Built:** request validation (Pydantic); CORS restricted to the frontend origin; secrets only in per-service `.env` files (never committed); `pydantic-settings` validates config at startup.
- **Planned:** rate limiting on `POST /api/queries`; CI dependency scanning; prompt-injection mitigation for text coming from data files (the planned fixed plan vocabulary limits what injected text could do).
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
| Who computes numbers | Code, never an LLM | Every number stays verifiable |
| Task queue | SAQ (Redis) | Async-native; Celery is too heavy; arq is in maintenance mode |
| Real-time transport | SSE | The trace only flows server -> client; plain HTTP with built-in browser reconnect. The brief mentions WebSocket; SSE serves the same purpose |
| Database | PostgreSQL only | Unit tests mock the database; integration tests use real Postgres, so a second engine adds nothing |
| Dataset rows | Read from files at query time | Faster than Postgres at current size (benchmarked); revisit if filtering moves into SQL |
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
