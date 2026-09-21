# Architecture -- Agentic Policy Data Analytics Platform

> **Status: living draft.** This document reflects the design as planned prior to implementation. It will be updated as the build proceeds (M1-M4) to stay accurate to what's actually built -- see `solutioning.md` for the full decision history and rationale behind every choice below.

## 1. System Overview

A full-stack agentic system that takes a natural-language policy research query, runs it through a multi-agent pipeline (plan -> extract -> analyze -> report -> validate), and returns a cited, chart-backed report -- with the agents' reasoning/action/observation steps streamed to the frontend in real time as the run progresses.

```
+-------------+   REST (submit query)    +-------------+
|  Frontend   | -----------------------> |   Backend    |
|  (Next.js)  |                          |  (FastAPI)   |
|             | <---- WebSocket (trace)- |              |
+-------------+                          +------+-------+
                                                 |
                                                 | enqueue
                                                 v
                                          +------+-------+          +-------------+
                                          |    Worker     | <------> |    Redis     |
                                          | (arq, runs    |          | (queue +     |
                                          |  LangGraph)   |          |  pub/sub)    |
                                          +------+-------+          +-------------+
                                                 |
                                                 | persists
                                                 v
                                          +-------------+
                                          |  PostgreSQL  |
                                          +-------------+

Worker also calls out to:
  - LLM providers (OpenAI / AWS Bedrock) via a swappable provider factory
  - Local dataset files under backend/data/incoming/ (SingStat / MOM / data.gov.sg exports)
```

**Why this shape**: the API process only ever handles fast operations (submit query, serve history, relay WebSocket frames). All slow work -- the actual LangGraph run, which may involve multiple LLM calls and file parsing -- happens in a separate `worker` process. This keeps the API responsive under load and is what makes real-time trace streaming actually work across processes (an in-memory queue inside a single FastAPI process would not survive multiple workers/replicas).

## 2. Agentic Design (LangGraph)

### 2.1 Agent roster

Five agents -- the three required by the brief, plus two added to strengthen the design:

| Agent | Required? | Responsibility |
|---|---|---|
| **Data Coordinator** | Yes | Receives the NL query, produces a structured plan (`PlanStep[]`) -- which datasets to pull, what analysis to run |
| **Data Extraction** | Yes | Executes the plan against locally-provided dataset files, normalizes to DataFrames with provenance metadata |
| **Analytics** | Yes | Runs statistical analysis (trends, YoY, correlation) via pandas/numpy, produces grounded `Finding[]` |
| **Report Writer** | Added | Turns findings + citations into the natural-language report and chart specs; every claim must cite a `dataset_id`/`field` |
| **Validator / QA** | Added | Hallucination/grounding guard -- cross-checks every numeric claim in the report against the actual extracted data |

**Why 5, not 3**: the spec requires a minimum of 3 and explicitly grades "how thoughtfully have you designed the agent architecture." Report Writer and Validator aren't padding -- Report Writer separates "what the data says" (Analytics' job) from "how to explain it" (an LLM-synthesis job with different failure modes), and Validator is the concrete mechanism behind the spec's required hallucination-detection testing (see Section 6) -- it's not a test-only concept, it's a real node in the graph with a bounded retry loop.

### 2.2 Shared state

All agents operate on a single shared `AgentState` object (not isolated agent-to-agent messages), so every intermediate artifact is inspectable -- useful for debugging, for the live-demo "explain your architecture" ask, and for tests that assert on state directly.

```
AgentState
 |-- query, session_id, run_id
 |-- provider_override          # user's explicit LLM provider choice, if any
 |-- plan: PlanStep[]            # from Coordinator
 |-- raw_extracts: RawExtract[]  # from Extraction (per source)
 |-- clean_data: CleanedDataset[]
 |-- findings: Finding[]         # from Analytics -- atomic grounded claims
 |-- report_markdown, chart_specs
 |-- validation_report           # grounded: bool, flagged_claims, retry_count
 |-- trace_events: TraceEvent[]  # append-only reasoning/action/observation log
 `-- errors: AgentError[]        # accumulated, non-fatal -- partial results still return
```

### 2.3 Graph flow

```
START -> coordinator -> extraction (retry loop per source)
                             |
                             v
                         analytics
                             |
                             v
                    +--> report_writer
                    |            |
    (ungrounded claim,           v
     retry_count < 2)        validator
                    |            |
                    +------------+
                                 |
                                 v
                (grounded, or retries exhausted -> low-confidence flag)
                                END

Any node --(unrecoverable failure)--> error_handler -> END
```

Built with `langgraph.graph.StateGraph` and conditional edges; `langgraph.checkpoint.MemorySaver` used in dev for run inspection/replay.

### 2.4 ReAct visibility / real-time trace streaming

Every node calls `emit_trace(state, step_type, content)` where `step_type in {reasoning, action, observation}`. The worker runs the graph via `.astream(stream_mode="values")`, publishing each new trace event to a Redis pub/sub channel keyed by `run_id`. The FastAPI `WS /ws/agent-trace/{run_id}` route relays these to the connected frontend client as they happen.

This is what satisfies the spec's "real-time agent activity monitoring showing reasoning steps" (frontend) and "WebSocket support for real-time updates" (backend) -- they're two halves of one mechanism, not two separate features.

### 2.5 Failure handling

- **Tool-level errors** (e.g., a dataset file fails to parse) are caught inside the tool wrapper and appended to `state.errors` as a typed `AgentError` -- the graph continues with whatever succeeded rather than crashing. Partial results are always preferable to total failure.
- **Extraction** retries per-source before giving up on that source specifically (other sources still proceed).
- **LLM-level errors** are handled separately by the provider fallback layer (Section 3), not by the graph itself.
- **Unrecoverable failures** (e.g., zero sources succeeded and all LLM providers are down) route to a dedicated `error_handler` node, which produces a clear partial/failed status rather than an opaque crash.

## 3. LLM Provider Abstraction (Multi-Cloud)

### 3.1 Design

```python
get_chat_model(provider: ProviderName, model_tier: Literal["fast", "quality"], **overrides) -> BaseChatModel
```

Agent code never imports a provider SDK directly -- only this factory (`backend/app/llm/provider_factory.py`). `ProviderName` enum: `openai`, `bedrock` today; `azure_openai`/`vertex_ai` stubbed (`NotImplementedError`) to demonstrate the abstraction is genuinely extensible, not hardcoded to two providers.

**Provider resolution order**: explicit per-request override -> session setting -> environment default. This is what makes "user can switch LLM providers" a real, user-facing capability (a dropdown in the query UI) rather than an internal implementation detail.

**Model tier** (`fast` vs. `quality`) is a separate axis from provider -- see Section 7 (Non-Functional Requirements) for why.

### 3.2 Providers

- **OpenAI** -- `langchain_openai.ChatOpenAI`.
- **AWS Bedrock** -- `langchain_aws.ChatBedrockConverse` (the Converse API normalizes tool-calling across Bedrock's different underlying model families). Requires an AWS account, Bedrock model-access approval, and IAM credentials with `bedrock:InvokeModel` -- a real setup dependency the user provisions themselves, documented in README/DATA_SOURCES.md. `LLM_ENABLE_BEDROCK=false` is an escape hatch so local dev without AWS access still runs end-to-end on OpenAI alone.

### 3.3 Fallback

Distinct from user-driven switching (Section 3.1): a fallback wrapper wraps the resolved primary model, and on transient/auth/connection errors automatically retries against the configured secondary provider (`tenacity`, max 2 attempts/provider, exponential backoff), logging a `ProviderFallbackEvent` into `trace_events` -- visibly demoable ("OpenAI failed, retried on Bedrock"). The spec requires both user-driven switching *and* automatic fallback; they are deliberately separate mechanisms here.

### 3.4 Secrets

Each service owns its own environment file -- `backend/.env.example` and `frontend/.env.example` -- rather than a single shared root file, matching the standard per-service pattern for a Docker-based monorepo (Section 9.1): each Dockerfile only ever concerns itself with its own app, so config ownership follows the same boundary. `.gitignore` excludes both real `.env` files; `pydantic-settings` validates required backend config at startup, but only for providers that are actually enabled; Docker Compose passes secrets via a per-service `env_file`, never baked into images.

## 4. Data Extraction Layer (File-Based)

### 4.1 Why file-based, not live API

Originally scoped as live integration against the SingStat and data.gov.sg public APIs. Revised after research surfaced two real, unresolved gaps: data.gov.sg's `q` free-text search parameter has documentation that contradicts at least one independently-reported observed behavior ("q is invalid"), and SingStat's search-matching semantics (case sensitivity, substring vs. exact) are undocumented anywhere found. Rather than build against assumed API behavior, extraction is file-based: the user downloads real datasets (JSON/CSV) from SingStat, MOM Statistics, and/or data.gov.sg and provides them locally. Full rationale in `solutioning.md` Section 7.

This is not a lesser design -- it satisfies the spec's requirements just as directly (>=2 real government sources, multiple formats, error handling for missing/malformed data, data-quality validation) while removing rate-limiting and undocumented-behavior risk from the critical path and the live demo, and giving full control over data shape for deterministic tests.

**Update**: live API integration is no longer purely deferred -- see Section 4.5. Live testing against data.gov.sg's Datastore Search API (with a known `resource_id`, not free-text search) confirmed the endpoint, `filters`, and pagination all work exactly as documented. Testing from the development sandbox's network saw intermittent 403s (Cloudflare bot-challenge) even with browser-realistic headers and request spacing; a follow-up test of the same script (unmodified, including zero custom headers) run from the developer's own network returned 13/13 successes, including repeated requests and session reuse. **Conclusion: the blocking observed was specific to the sandbox environment's IP/network reputation, not a property of the API itself.** From a normal residential/office network -- which is what a live demo would run from -- this API behaves as a reliable, well-documented, low-friction data source. This meaningfully de-risks the live-API mode described in Section 4.5; the `api_fallback: file` design is retained regardless, as defense-in-depth against network-dependent variance (e.g. if the demo machine happens to be on a flagged network), not because the API itself is expected to be unreliable. Full test evidence in `solutioning.md`.

### 4.2 Ingestion model

```
backend/data/incoming/
  singstat/
    <dataset files>.json
  mom/
    <dataset files>.csv
  data_gov_sg/
    <dataset files>.json

backend/data/manifest.yaml   # catalog: source, title, file_path, format, topic/keywords, column_meta
```

The manifest is what the Coordinator and Extraction agents reason over to match a query to relevant files -- it's the file-based stand-in for what a live search API would otherwise provide.

### 4.3 Interface stability

Both the current file-loader and any future live-API client implement the same `DataSourceClient` protocol (`fetch(query) -> RawExtract`). Today it resolves against the manifest + local filesystem; a future implementation could resolve against a real HTTP endpoint instead, without the Extraction Agent's tool-calling logic changing at all.

### 4.4 Parsing, validation, error handling

- **Parsers**: `json_parser.py`, `csv_parser.py` (pandas), `excel_parser.py` (openpyxl, for `.xlsx` if provided) -- all normalize to a common `CleanedDataset` shape (DataFrame + column metadata + units + source citation).
- **Error handling**: file-not-found, malformed/unparseable file, schema-mismatch-against-manifest, empty file -- each is a caught, typed error appended to `state.errors`; the run continues with whatever files succeeded. This is the file-based analog of "API failure handling," fully reproducible on demand (point the manifest at a deliberately corrupted fixture).
- **Validation/cleaning**: **pandera** (`DataFrameSchema` per dataset shape) plus custom quality checks -- outlier flagging (z-score/IQR), completeness ratio, duplicate detection -- producing a `DataQualityReport` surfaced in the UI's quality panel.
- **Caching**: cleaned datasets persisted to Postgres keyed by content hash, so repeat queries reuse results without re-parsing.

### 4.5 Per-dataset source mode: file vs. live API

Rather than a single global "file-based or live API" switch, **each dataset declares its own source mode in the manifest** -- some datasets load from the provided file, others query data.gov.sg live, configured declaratively, not decided per query:

```yaml
# backend/data/manifest.yaml (illustrative)
datasets:
  - id: retrenchment_by_industry
    source: data_gov_sg
    mode: file                          # file | api
    file_path: incoming/data_gov_sg/NumberofRetrenchedEmployeesbyIndustryandOccupationAnnual.csv
    resource_id: d_6d1fcbd205b908c27c174db08432346a   # kept even in file mode, for provenance/citation

  - id: job_vacancy_by_industry
    source: data_gov_sg
    mode: api                           # this one queries live instead
    resource_id: d_889d11a2b0a53b235abb64e3f4e0a47b
    api_fallback: file                  # if the live call fails, fall back to this:
    file_path: incoming/data_gov_sg/NumberofJobVacancybyIndustryandOccupationAnnual.csv
```

Only pre-vetted `resource_id`s already listed in `DATA_SOURCES.md` are ever queryable in `api` mode -- this is filter/paginate-only access to known tables, never free-text/dynamic dataset discovery (the `q`-param search that was rejected in Section 4.1 stays rejected; this is a narrower, safer capability than what was originally considered and dismissed).

Both modes are implementations of the same `DataSourceClient` protocol (Section 4.3):
- **`file` mode** -- `FileDataSourceClient`: reads from `file_path`, as already designed (Sections 4.2, 4.4).
- **`api` mode** -- `ApiDataSourceClient`: calls data.gov.sg's `datastore_search` with `resource_id` + `filters` + `limit`/`offset` (confirmed working live -- see Section 4.1 update -- reliably, from a normal network; no special User-Agent handling turned out to be necessary once tested from a non-sandboxed network). On any failure (403, timeout, non-200, malformed JSON) -- **not just retried, but transparently downgraded**: if `api_fallback: file` is set, the Extraction Agent serves the file-backed data instead and tags the result `source_mode: file_fallback` in `trace_events` and the response, so the UI can show "live data unavailable, showing cached dataset" rather than either crashing or silently pretending the live call succeeded. If no fallback file is configured for an `api`-mode dataset, the failure is a normal `AgentError` (Section 2.5) like any other extraction failure.

This is deliberately **not** a per-query toggle (e.g. a user-facing "live vs. cached" switch on every question) -- source mode is a property of the dataset, set once in the manifest, because reliability differs genuinely by dataset/resource_id, not by the phrasing of a given query. It reuses the existing `DataSourceClient` abstraction exactly as intended (Section 4.3), needs no change to the Extraction Agent's tool-calling logic. The `api_fallback` mechanism is kept as defense-in-depth (network conditions can still vary, e.g. a firewalled/corporate network) rather than as compensation for an unreliable API -- live testing (Section 4.1) showed the API itself is reliable from a normal network.

## 5. Database Schema

**PostgreSQL** (via Docker Compose) as primary, SQLAlchemy ORM + Alembic migrations; **SQLite** as a zero-setup fallback for fast unit tests without Docker.

| Table | Purpose |
|---|---|
| `datasets` | source, title, fetched_at, format, raw_cache_path, content_hash, `quality_report` (JSONB) |
| `analysis_runs` | session_id, query_text, query_hash (for response-cache lookups, Section 7.2), provider_used, status, timestamps, report_markdown, `chart_specs` (JSONB), `token_usage` (JSONB, per-call breakdown), `estimated_cost_usd` |
| `analysis_run_datasets` | join table -- which datasets a run cited |
| `agent_traces` | persisted copy of the streamed trace, enabling history/export replay |
| `findings` | metric, value, unit, confidence, `dataset_id` FK, field_ref -- the atomic grounded claims the Validator cross-checks against |
| `sessions` | lightweight; no real auth needed for this scope |

Indexes on `run_id`, `session_id`, `created_at` are included from the first migration (see Section 7).

## 6. Backend Design (FastAPI)

**Why FastAPI**: async-native (matches `httpx`/LangGraph streaming), native WebSocket support, and Pydantic schemas align directly with LangGraph's state model.

**Key endpoints**:
- `POST /api/queries` -- submit a query (+ optional provider override); returns `202` + `run_id`.
- `GET /api/queries/{run_id}` -- poll fallback if the WebSocket connection drops.
- `WS /ws/agent-trace/{run_id}` -- live trace stream.
- `GET /api/analyses` / `GET /api/analyses/{run_id}/export?format=pdf|json|csv` -- history and export.
- `GET /api/datasets`, `GET /api/datasets/{id}` -- provided dataset catalog.
- `GET /api/health`, `GET /api/health/providers` -- liveness + per-provider status.

**Async task processing**: **arq** (Redis-backed), chosen over Celery (too heavy for this scope) and over FastAPI's plain `BackgroundTasks` (no persistence, no retry, no cross-process visibility -- insufficient once trace streaming needs to survive across separate API/worker processes). Redis doubles as both the arq broker and the WebSocket trace pub/sub channel -- one piece of infrastructure serving two purposes deliberately, not incidentally.

## 7. Non-Functional Requirements

The spec names no explicit NFR targets, but several were locked in deliberately rather than left to "tune later," since they affect the agent graph's structure and would be wasteful to retrofit after M2.

### 7.1 Performance / Latency

- **Target**: first `TraceEvent` visible over WebSocket within 2 seconds of query submission -- proves the async path isn't silently blocking before the user sees anything.
- **Target**: a simple, single-source query completes end-to-end within 60 seconds under normal conditions.
- Both become Locust/integration-test assertions, not just descriptive load-test output (see `TESTING.md` once written).
- `run_id`, `session_id`, `created_at` are indexed from the first migration.

### 7.2 Cost Management

Cost hadn't been addressed as its own topic until raised explicitly post-M0-planning; several techniques were already implicit in earlier decisions (made for other reasons) and are named here explicitly, alongside new items added to the core build.

**Already part of the design, now recognized explicitly as cost optimization:**
- **LLM model tiering** -- not every agent step needs the strongest model. The provider factory (Section 3.1) takes a `model_tier` parameter: **`fast`** for the Coordinator's planning step and Extraction's tool-selection reasoning (lower stakes, higher volume of calls), **`quality`** reserved for Analytics' insight generation and Report Writer's final synthesis (where correctness and hallucination risk matter most). Resolved to concrete model ids per provider via `.env` (e.g. `OPENAI_MODEL_FAST` vs. `OPENAI_MODEL_QUALITY`). The single biggest cost lever available in this design.
- **Content-hash caching of cleaned datasets** (Section 4.4) -- avoids redundant parsing work on repeat queries against the same data.
- **File-based extraction instead of live API** (Section 4.1) -- decided for reliability/determinism reasons, but a side effect is that there's no live API to retry against, removing a class of "agent burns tokens retrying a flaky call" scenarios entirely.
- **Prompt/context trimming, implicitly** -- the Extraction Agent normalizes raw files into `CleanedDataset`s and the Analytics Agent produces atomic `Finding[]` records rather than passing whole raw datasets downstream; the Report Writer's prompt is built from findings, not raw file contents. This was designed for data-flow clarity, but it also means the LLM is never handed more context than the specific slice relevant to the step at hand -- now called out explicitly as a cost technique, not left as an unstated side effect.

**Added to the core build:**
- **Cost/token tracking per run** -- the provider factory (Section 3.1) is the single choke point every LLM call passes through, so it's the natural place to capture token usage (input/output) and estimated `$` cost (via a per-model pricing lookup table) on every call. Recorded on the `analysis_runs` record (new `token_usage` / `estimated_cost_usd` columns, Section 5) and surfaced in the UI (e.g. "this query used ~2,400 tokens, ~$0.03") -- a concrete, demoable answer to the Innovation Assessment's "cost optimisation" prompt rather than a paper-only claim.
- **Response caching on repeat queries** -- extends the same `content_hash` pattern already used for datasets (Section 4.4) to `analysis_runs`: an identical (or near-identical, via normalized query text) query returns the cached report instead of re-running the full agent graph, with a "cached result" indicator in the UI so it's not mistaken for a fresh run.
- **Per-agent-step token budgets** -- a `max_tokens` cap set per node (e.g., the Coordinator's planning output doesn't need a 4000-token budget), configured alongside `model_tier` in the provider factory call. Bounds worst-case cost per run, not just average cost.

**Deferred to the Innovation Assessment (not built, see Section 12):** provider-native prompt caching (OpenAI and Bedrock/Anthropic both support this for repeated prompt prefixes) and semantic/embedding-based query deduplication.

### 7.3 Security

Baseline (proportionate to a take-home, not over-engineered): Pydantic validation on every route; secrets never committed; rate limiting on `POST /api/queries` (`slowapi`, Redis-backed) to prevent runaway LLM-cost abuse; CI dependency scanning; explicit CORS configuration even in dev.

Additional items identified but **not yet fully designed** (flagged, see Section 7.5):
- Least-privilege IAM and non-public RDS/Redis for the one-time cloud deployment validation (Section 9).
- **Prompt injection via extracted file content** -- a CSV/JSON cell could contain text engineered to manipulate an agent's prompt when that data is interpolated in. This is a real, currently-unmitigated risk given the system's "input" includes third-party file content, not just the user's query. Needs a concrete mitigation (e.g., structured tool outputs instead of raw string interpolation, or a sanitization pass) -- deferred to a dedicated design discussion.

Production-grade extras (SSO/RBAC, audit logging, VPC isolation) are intentionally out of scope for the build itself and addressed only in the written Innovation Assessment.

### 7.4 Privacy

Currently minimal, stated explicitly rather than left implicit (the domain -- government/policy data -- makes silence here conspicuous):
- **Assumption**: all provided datasets are public, aggregate-level government statistics, not individual/row-level records -- so no PII is expected to flow through the pipeline. This will be stated explicitly in `DATA_SOURCES.md`.
- A "what production would need" note (row-level access controls, classification tagging, PII scanning on ingest) is planned for the Innovation Assessment.

### 7.5 Open items -- not yet designed

Two items are deliberately left open pending a dedicated follow-up discussion, not resolved by default:
1. **Privacy posture in depth** -- whether any technical controls belong in the build itself versus staying a documentation-only discussion.
2. **LLM guardrails** -- the concrete mechanism for prompt-injection mitigation from extracted-data content, and whether output-side filtering/moderation is warranted.

This section will be updated once that discussion happens.

## 8. Frontend Design (Next.js + TypeScript)

- **Charting**: Recharts, with Plotly.js as a fallback if richer statistical chart types are needed (decided at M2 based on what the Analytics Agent actually produces).
- **State**: TanStack Query for REST caching/retry; Zustand for cross-component UI state (selected run, active provider).
- **Real-time trace**: `useAgentTrace(runId)` WebSocket hook, falling back to polling `GET /api/queries/{run_id}` if the socket drops -- resilience for the live demo.
- **Query input**: NL text input plus an explicit provider selector (OpenAI / Bedrock / Auto-fallback) -- the visible UI surface for the runtime-switchable-provider requirement, not buried in settings.
- **Dashboard**: findings cards, a chart panel driven entirely by backend-returned `chart_specs` JSON (not hardcoded chart types), a citations panel linking every claim to its source dataset, and a data-quality panel (completeness %, outliers flagged, rows dropped).
- **History/export**: a `/history` page listing past runs, each exportable as PDF/JSON/CSV.

## 9. Deployment

### 9.1 Containerization (the actual submission artifact)

The grader's hands-on path is **local only**: `git clone` -> copy `backend/.env.example` to `backend/.env` and `frontend/.env.example` to `frontend/.env` -> `docker compose up` -> the full stack (frontend, backend, worker, Postgres, Redis) is live on `localhost`. No image is pushed to a registry; no service is hosted anywhere for grading purposes.

- `frontend/Dockerfile` -- multi-stage (deps -> build -> `next start`/standalone runtime).
- `backend/Dockerfile` -- multi-stage; the same image is reused for both the API process and the arq worker process (different `CMD` per Compose service), avoiding a duplicate Dockerfile.
- `infra/docker-compose.yml` -- `frontend`, `backend`, `worker`, `db` (postgres:16), `redis` (redis:7), health-check-gated startup ordering.
- Each service has its own `.env.example`, per Section 3.4 -- `docker-compose.yml` points each service's `env_file` at its own app's `.env`, not a shared root file. `docker-compose.override.yml` layers on dev-only hot-reload bind mounts without touching the base compose file's prod-shaped structure.

### 9.2 Scope note on "multi-cloud"

Every use of "multi-cloud" in the requirements is scoped to LLM providers (Section 3), never to hosting infrastructure. Section 8 of the brief (DevOps & Deployment) asks only for Docker/Compose, a CI/CD pipeline, "environment management and secrets handling," and "clear deployment documentation" -- none of which require an actual multi-cloud (or any real) deployment. "Multi-cloud" is fully and correctly satisfied by the LLM provider layer alone.

### 9.3 Environment management & secrets handling

Satisfies the spec's explicit Section 8 bullet. Backend configuration flows through one central point (`backend/app/core/config.py`, `pydantic-settings`), which validates required variables at startup -- but only for whichever LLM providers are actually enabled, so local dev without AWS access still works. Each service's `.env.example` (`backend/.env.example`, `frontend/.env.example`) documents that service's own variables; neither real `.env` is ever committed. In a real cloud deployment, the same variables would be injected via AWS Secrets Manager or Azure Key Vault instead of a `.env` file -- the application code doesn't need to know which, since it only ever reads from environment variables through the settings layer.

### 9.4 A path to real cloud hosting (documented, and validated once -- see Section 9.5)

Because the app is fully containerized, the same images are portable to any container-hosting platform with no code changes. What *would* differ per cloud:

- **AWS** -- push images to ECR; run via ECS/Fargate (simpler) or EKS (if going Kubernetes); Postgres/Redis become RDS/ElastiCache; secrets move to Secrets Manager; Terraform (or CDK) describes it as code.
- **Azure** -- push images to ACR; run via Container Apps (architecturally closest to Compose) or AKS; secrets move to Key Vault; Bicep or Terraform describes it as code.
- **The LLM provider layer** is the one place cloud choice is inherently significant -- AWS Bedrock is an AWS-specific dependency. If ever moving away from AWS entirely, Bedrock would be swapped for another provider (Azure OpenAI, GCP Vertex) via the provider factory (Section 3) -- a config/implementation addition, not an architectural rewrite, since that abstraction exists precisely for this reason.

### 9.5 Cloud deployment validation (one-time, disposable -- M3.5)

"Clear deployment documentation" will be validated once against a real environment rather than written speculatively. A one-time, disposable deployment to AWS (dev-tier: ECS/Fargate, RDS, ElastiCache, Secrets Manager) will be built by literally following this document's deployment steps, fixing them until the deploy genuinely works end-to-end (a real query executes successfully against the live deployment), with evidence captured (recording/logs). All cloud resources are then torn down to avoid ongoing cost -- this validates the documentation without becoming a persistent hosted instance the grader depends on. IaC/steps used are committed under `infra/cloud/` so the validated path is reproducible, not just narrated, and can be re-run on request.

Least-privilege IAM (a scoped role limited to `bedrock:InvokeModel` and whatever RDS/Secrets Manager access is strictly needed) and non-public RDS/Redis are required for this deployment -- not optional, given the domain.

## 10. Milestones / Build Order

The build is sequenced so a working increment exists early, even though the final deliverable must cover every requirement in the spec. Refreshed to reflect decisions made since the original sequencing (real dataset scope, per-dataset file/API mode, cost tracking, ETL execution model) -- see `solutioning.md` for the full history of each.

### 10.1 ETL execution model (resolved)

Two different mechanisms for two genuinely different data-quality situations, not a hedge between them:

- **`file`-mode datasets** (Section 4.5) have known, specific, structural messiness diagnosed by hand (Section 14 of `solutioning.md`): inconsistent sentinels (`-`, `na`), MOM sheet footers, a sheet-naming scheme that changed across years, a classification break partway through the retrenchment series. This needs **deterministic, pre-written rules**, not per-query LLM judgment -- a one-time seed script (`backend/scripts/seed_datasets.py`) runs the full pipeline (parse -> normalize -> sentinel-handle -> filter to decided scope -> pandera-validate -> load) once against `backend/data/incoming/`, idempotent on first container start (skips re-seeding if the content hash is unchanged), re-runnable manually if source files change. Agents query Postgres only; raw files are never re-parsed at query time.
- **`api`-mode datasets** (Section 4.5) return already-clean, already-typed JSON straight from data.gov.sg's Datastore Search API -- no footers, no merged cells, no sheet drift, nothing to deterministically pre-clean. What's actually needed is query-time judgment (which filters, which fields, how to shape the request for *this* question), which is what the Extraction Agent does live, per query, calling the API directly (schema is already known from the manifest/`DATA_SOURCES.md`, so minimal blind discovery is needed), with `api_fallback: file` as the safety net on failure.

### 10.2 Milestones

| Milestone | Scope |
|---|---|
| **M1 -- Walking skeleton** | Repo scaffolding, `.env.example`, minimal Docker Compose (frontend + backend + db). The one-time seed script (Section 10.1) runs against the real, already-provided datasets (retrenchment/vacancy/graduate-survey CSVs + MOM F2 sheets 2023-2025, per `DATA_SOURCES.md`) for at least one file-mode dataset. A single combined agent, one LLM provider (OpenAI). Minimal UI: submit a query, see a raw result. Goal: prove the full request path end-to-end, including a real seeded dataset, before adding complexity. |
| **M2 -- Full agentic core** | The real 5-node LangGraph (Section 2). Seed script covers the full file-mode dataset scope; at least one `api`-mode dataset wired up with live extraction + `api_fallback: file` (Section 4.5) verified working both ways (live success and forced-failure fallback). Both LLM providers via the factory + fallback (Section 3), provider selector live in the UI. Cost/token tracking, response caching, and per-agent-step token budgets (Section 7.2) implemented -- not deferred. arq/Redis worker; WebSocket trace streaming live. Full dashboard (charts, citations, data-quality panel, cost/token display). Full DB persistence, history page. |
| **M3 -- Quality, tests, DevOps** | Full test suite (unit, integration, hallucination/consistency/accuracy, data quality, Locust load test) -- including tests for both ETL paths (seed-script correctness against the known sentinel/footer/classification-break fixtures, and the live-API path's fallback-on-failure behavior). CI pipeline green. Docker Compose and Dockerfiles finalized, security basics in place. All four required docs (README, ARCHITECTURE, TESTING, DATA_SOURCES) completed, including a first draft of this document's Deployment section. **Explicit checkpoint**: privacy/LLM-guardrail design and the observability stretch goal (Section 7.5, Section 12) are either resolved or consciously, explicitly deferred with a one-line rationale recorded -- not left to fall through silently. |
| **M3.5 -- Cloud deployment validation (one-time, disposable)** | Stand up the documented deployment path against a real AWS dev-tier environment, following Section 9 as written; fix the doc until the deploy genuinely works end-to-end; capture evidence (recording/logs); commit IaC under `infra/cloud/`; **tear down all cloud resources** afterward. The grader's actual path stays local-only (Section 9.1) -- this milestone exists purely to make the deployment documentation trustworthy, not to provide a persistent hosted instance. Explicitly time-boxed; if it overruns, the fallback is documented-but-unvalidated deployment docs rather than eating into M3/M4 time. |
| **M4 -- Polish / stretch** | Export finalized if not done in M2. Bonus items in priority order (see Section 12: Future Work). Innovation Assessment write-up. Demo rehearsal against the README's sample queries, **including the deliberate live-API showcase moment** (Section 4.5's "Demo plan"). |

Verification checkpoints for each milestone (what "done" concretely looks like) are tracked alongside the execution plan; see `solutioning.md` for the full reasoning behind why the sequence is shaped this way (particularly M3.5, which was added after the core plan was first approved, and the ETL model in Section 10.1, resolved after reviewing a reference implementation).

## 11. Key Design Tradeoffs

| Decision | Chosen | Alternative considered | Why |
|---|---|---|---|
| Async task queue | arq (Redis-backed) | Celery | Celery's broker/worker/beat machinery is disproportionate overhead for this scope; arq is async-native (fits FastAPI directly) and Redis doubles as the trace pub/sub broker |
| Data validation | pandera | great_expectations | Code-first, lightweight, proportionate to scope; GE's config/context overhead isn't justified here |
| Agent count | 5 (3 required + 2 added) | Exactly 3 | Report Writer and Validator aren't padding -- Validator is the literal hallucination-detection mechanism the testing requirements need; splitting "what the data says" from "how to explain it" is a real separation of concerns |
| Data extraction | File-based by default, per-dataset live API opt-in (Section 4.5) | Fully file-based, or fully live API | Both public APIs had real, unresolved documentation gaps (contradictory `q`-param behavior, undocumented search semantics) discovered during research; building against assumptions was rejected in favor of a deterministic, fully-controlled default -- live API was reconsidered once narrowed to pre-vetted resource_ids only, and live-tested as reliable from a normal network, so it's now an opt-in per-dataset mode rather than fully deferred (Section 4.1, Section 4.5, Section 10.1) |
| LLM providers | OpenAI + AWS Bedrock | OpenAI + Gemini | Bedrock is a literal cloud platform (not just an API), a stronger and more literal answer to "multi-cloud LLM integration" than two API-key-only services |
| Cloud hosting | None (local Docker Compose only) + one-time validated deployment docs | Persistent live deployment | Spec doesn't require hosting; a persistent deployment adds ongoing cost and a pre-demo failure surface without being asked for -- but *undocumented* deployment instructions are also a real risk, hence the one-time validate-and-tear-down approach (Section 9.5) |
| Provider fallback vs. user switching | Both, as distinct mechanisms | Fallback only | Spec requires both "user can switch providers" and "demonstrate fallback" -- conflating them would under-deliver on one or the other |

## 12. Future Work (explicitly deferred)

- **Live API integration against data.gov.sg: now scoped into the core build for pre-vetted resource_ids** (Section 4.5), not fully deferred -- per-dataset `file`/`api` mode with automatic fallback to file on failure. Still deferred: SingStat live integration (its search-matching semantics remain unconfirmed, per Section 4.1), and any data.gov.sg free-text/dynamic dataset discovery (only fixed, pre-vetted `resource_id`s are ever queried live).
- **Full privacy posture and LLM guardrail design** (Section 7.5) -- currently flagged, not designed.
- **Provider-native prompt caching** (OpenAI and Bedrock/Anthropic both support caching repeated prompt prefixes, e.g. a long system prompt or shared dataset context reused across Analytics -> Report Writer -> Validator) -- a real, provider-specific cost lever not yet implemented; a strong Innovation Assessment talking point given it differs slightly per provider, tying directly into the multi-cloud framing.
- **Semantic/embedding-based query deduplication** -- detecting "this is essentially the same question, differently worded" beyond exact-match response caching (Section 7.2); would require a vector store, so folded into the existing RAG/vector-DB stretch goal rather than built standalone.
- **Bonus items**, in priority order if time allows: streaming token-level report output, vector DB/RAG over past analysis runs (now including the semantic dedup use case above).
- Discussed on paper (not built) in the Innovation Assessment: adaptive replanning on stale/unavailable sources, a confidence+citation UI pattern for analyst trust, cross-team knowledge sharing via RAG, cost-aware provider routing, and production-grade security (SSO/RBAC, audit logging, VPC isolation, data classification).

---

*See `solutioning.md` for the full discussion and reasoning trail behind every decision in this document.*
