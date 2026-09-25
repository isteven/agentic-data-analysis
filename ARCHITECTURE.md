# Architecture -- Agentic Policy Data Analytics Platform

> **Living document.** Every section states what is **built** today and what is **planned**. Status as of 2026-09-25: milestone M1 complete, M2 in progress.

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
data.gov.sg Datastore API (client built, no dataset uses it now), local dataset files (backend/data/incoming/).
```

**Today:** the backend runs the whole pipeline synchronously inside `POST /api/queries` and returns the full report and trace in one response. The worker task exists but nothing enqueues it yet, and there is no SSE route.

**Why this shape:** the API process only does fast work (accept a query, serve history, relay the trace stream); the slow work (several LLM calls, data loading) runs in a separate worker, so the API stays responsive and the trace can stream across processes.

## 2. Status by layer

| Layer | Target | Built today | Status |
|---|---|---|---|
| Frontend | Next.js + TypeScript, Recharts, TanStack Query | Next.js + TypeScript: one query page plus an agent-trace panel | Partial |
| Backend API | FastAPI: 202 + background run, SSE, history, export | FastAPI: synchronous `POST /api/queries`, health routes | Partial |
| Agent pipeline | LangGraph with loops (SQL retry, quality review) -- section 3.2 | LangGraph, 5 nodes in a straight line | Partial |
| Async / queue | SAQ worker on Redis | `run_query_task` built and publishes trace events; not wired to any route | Partial |
| Real-time trace | Redis pub/sub -> SSE | Trace returned once, after the run | Partial |
| LLM providers | OpenAI + AWS Bedrock, automatic fallback | OpenAI only; Bedrock stubbed | Partial |
| Data sources | data.gov.sg + MOM; CSV, Excel, live API | CSV + Excel from both sources; API client with file fallback built but unused since the dataset swap | Partial |
| Database | PostgreSQL | PostgreSQL, 7 tables + generated `data` views, Alembic migrations | Built |
| Visualisations | Charts driven by backend chart specs | None | Planned |
| History / export | History page; PDF / JSON / CSV export | None | Planned |
| Cost tracking | Tokens and estimated cost per run | None | Planned |
| Testing | Unit, integration, LLM accuracy / consistency, data quality, load | 62 unit tests | Partial |
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
| **extraction** | No | Loads each selected dataset: live data.gov.sg API with file fallback, or the local file; applies the shared cleaning (section 5.3) |
| **analytics** | No | Matches query words to category values, keeps non-overlapping rows (`default_slice`), sums the measure per year plus a first-to-last change; emits `Finding`s |
| **report_writer** | Yes (quality tier) | Writes the report from the findings only, citing the source dataset for each number |
| **validator** | No | Extracts every number from the report and checks it matches a finding (1% tolerance); appends a warning if any don't |

**Known limitations** (addressed by 3.2):

- Straight line: no agent looks at a result and decides what to do next.
- Analytics relies on hardcoded metric-column names and only sums; question wording is matched literally (no year ranges, no synonyms).
- The validator checks the report against the findings, not the findings against the truth: a wrong computation passes as "grounded".
- Only two nodes make decisions.

### 3.2 Planned: query-planning redesign (checked SQL)

```
intent -> coordinator -> planner -> SQL check -> run (read-only) -> report_writer -> number check -> quality review -> END
 (LLM)      (LLM)       (LLM:SQL) ^  (code)  |      (Postgres)          (LLM)           (code)          (LLM)
                                  +- retry --+                                                         |
             ^            ^                                                                            |
             +------------+----------------------- route back by root cause --------------------------+
```

| Step | LLM? | Responsibility |
|---|---|---|
| Intent | Yes | Rewrite the question precisely ("layoff" -> retrenchment, "past 3 years" -> 2023-2025); reject questions the catalog can't answer |
| Coordinator | Yes | Pick datasets |
| Planner | Yes | Write one PostgreSQL `SELECT` over the typed dataset views (section 5.4), or say the question can't be answered |
| SQL check | No | `sqlglot`: a single read-only `SELECT`; allowed views only; columns exist (with "did you mean" hints); no `SUM` on non-additive columns; views aggregated before joining. Errors go back to the planner (max 2 retries) |
| Run | No | Executed by Postgres as a read-only role that can see only the `data` views, with a statement timeout; every result value becomes a `Finding` |
| Report writer | Yes | Prose from findings only |
| Number check | No | Every number in the report must match a finding |
| Quality review | Yes | LLM judge: does the report answer the question, is anything misdescribed, were the right datasets used? Routes a failure back to the coordinator, planner or report writer |

**Principles:**
- LLMs interpret the question, choose what to compute and judge the result; **the database computes every number**. No LLM ever re-types data.
- **Data rules live in the views, not the prompt:** views expose only rows that are safe to add up (no total rows mixed with their parts, no overlapping categories). A spike showed prompt instructions alone did not stop double-counting; view shape did. The rules themselves are inferred from the data (section 5.5), not written per dataset.
- Column knowledge comes from the schema profiled at ingest (section 5.5), so the query path has no hardcoded column names or operation lists.

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

| Dataset | Source | Format | Coverage |
|---|---|---|---|
| `retrenchment_by_residential_status` | data.gov.sg | CSV | 2007-2025 |
| `mrt_to_junior_college_travel` | data.gov.sg | CSV | no time dimension (189 stations x 18 colleges) |
| `graduate_employment_survey` | data.gov.sg | CSV | 2013-2024 |
| `mom_usual_hours_by_occupation_{2023,2024,2025}` | MOM | Excel (sheet F2) | one file per year, one combined view |

The files are curated mock data derived from public downloads. Details and known data issues: `DATA_SOURCES.md`.

### 5.2 Manifest

`backend/data/manifest.yaml` catalogs every dataset with **metadata only**: `id`, `source`, `title`, `topic`, `mode` (`file` | `api`), `file_path`, `format`, `sheet_name`, `resource_id`, `api_fallback`, `group` (files that form one view), `year` (for files with no year column). The coordinator reads it to choose datasets.

Older entries still carry per-dataset rules (`column_meta`, `default_slice`) read by the pandas analytics path; they go away when the SQL planner replaces it. New datasets need none of them.

**Source mode is a property of the dataset, not a per-query switch.** `api` mode is only for pre-vetted data.gov.sg `resource_id`s.

### 5.3 Loading and cleaning

- **Parsers:** `csv_parser.py` (pandas; digit strings with a leading zero stay text, e.g. postal codes); `excel_parser.py` (openpyxl, built for the MOM F2 layout); `api_client.py` (data.gov.sg Datastore Search, pagination, 2 attempts with timeout).
- **Missing values:** `-`, `na`, `N.A.` and similar become missing, never 0.
- **Shared cleaning** (`app/data/cleaning.py`): adds `year` from the manifest where a file has none; still applies the legacy `min_year` / `default_slice` rules for the pandas analytics path.

### 5.4 Seeding and typed views

On startup the backend runs Alembic migrations, then `scripts/seed_datasets.py`:

1. **Prune:** datasets no longer in the manifest lose their stored rows; their catalog row is deleted unless a past analysis cites it.
2. **Seed:** each file is parsed, profiled (section 5.5) and written to `dataset_records` (one JSONB document per row), with a `datasets` catalog row. Skipped when the file hash and `PROFILER_VERSION` are unchanged.
3. **Views:** the `data` schema is dropped and rebuilt: one typed view per dataset (real `integer` / `double precision` / `text` columns), files sharing a `group` combined with `UNION ALL`, plus a `<view>_totals` view (additive measures summed per period) where there is something to sum.

Views are derived, so rebuilding them loses nothing. One generic table avoids a table per CSV. Reading through a JSON view is 2-7x slower than a typed table (about 1 ms at current sizes); materialized views close the gap past ~100k rows.

Today the query path still reads the files; the SQL planner will query the views.

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
| `dataset_records` | Every cleaned source row as a JSONB document; read through the generated views in the `data` schema | Written by seeding; to be queried by the SQL planner |
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
- Live API datasets are fetched in full on every query -> cache them (no dataset uses the API right now).
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
