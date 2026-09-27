# Agentic Policy Data Analytics

Ask a question about Singapore government statistics in plain English; a team of LLM agents picks the datasets, has the database compute the answer, writes a cited report with a chart, and checks it before you see it. Every step is shown live.

- **Data:** 6 files from data.gov.sg (CSV) and MOM (Excel), loaded into PostgreSQL. See [DATA_SOURCES.md](DATA_SOURCES.md).
- **Numbers come from the database, never the LLM.** Agents write SQL; the SQL is checked, then run read-only. Every number in the report is verified against the query result.
- **Two LLM providers** (OpenAI, AWS Bedrock) with automatic per-call fallback.

Architecture, agent pipeline and design decisions: [ARCHITECTURE.md](ARCHITECTURE.md).

## Demo

https://github.com/user-attachments/assets/9a829e78-75cb-4423-932f-7b6dbfeb8e82

## Setup & run

### Get the code

```bash
git clone https://github.com/isteven/agentic-data-analysis.git
cd agentic-data-analysis
```

All commands below start from this folder (the repository root).

### Docker Compose

Requirements: Docker, an OpenAI API key (also add AWS Bedrock access if you want to test both providers)

```bash
cp backend/.env.example backend/.env      # set OPENAI_API_KEY
cp frontend/.env.example frontend/.env
cd infra
docker compose up --build
```

Open http://localhost:3000. Startup migrates the database and loads the datasets automatically. Services: `db` (Postgres 16), `redis`, `backend` (:8000), `worker`, `frontend` (:3000).

- **Bedrock (optional):** set `LLM_ENABLE_BEDROCK=true`, AWS credentials and `BEDROCK_MODEL_ID_*` in `backend/.env`. Pick the provider per question in the UI; if one fails, the call retries on the other.
- **Frontend hot reload:** `docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build`

### Without Docker

Requirements: 
- PostgreSQL 16
- [uv](https://docs.astral.sh/uv/) (installs Python 3.12+ itself)
- Node.js 20
- OpenAI API key (Optional: AWS Bedrock access key). 
- Redis 7. On Windows, Redis has no official native build: run it in WSL or a container. If the Compose stack is running, stop it first (it uses the same ports: 5432, 6379, 8000, 3000).

Start the services in this order; the backend services each run in their own terminal.

**1. PostgreSQL:** create the app's user and database (as the `postgres` superuser, e.g. `psql -U postgres`):

```sql
CREATE ROLE apda LOGIN PASSWORD 'apda' CREATEROLE;
CREATE DATABASE apda OWNER apda;
```

`CREATEROLE` is needed once, by the migrations: they create the `data_reader` role that the agents' SQL runs as (read-only, views only). The user doesn't need to be a superuser.

**2. Redis:** start it on the default port and check it answers: `redis-cli ping` → `PONG`.

**3. Backend configuration:**

```bash
cd backend
cp .env.example .env
```

In `backend/.env`, set `OPENAI_API_KEY`, and point the two service URLs at `localhost` instead of the Compose service names:

```
DATABASE_URL=postgresql+asyncpg://apda:apda@localhost:5432/apda
REDIS_URL=redis://localhost:6379/0
```

**4. Backend dependencies** (from `backend/`): `uv sync`

**5. API** (terminal 1, from `backend/`):

```bash
uv run uvicorn app.main:app --port 8000
```

On startup it runs the database migrations and loads the datasets (a few seconds the first time; skipped later while the files are unchanged). Wait for `Application startup complete`, then check http://localhost:8000/api/health.

**6. Worker** (terminal 2, from `backend/`): runs the agents for each question.

```bash
uv run python -m saq app.worker.settings_dict
```

Check http://localhost:8000/api/health/ready: `database`, `redis` and `worker` should all be `ok`.

**7. Frontend** (terminal 3):

```bash
cd frontend
cp .env.example .env          # NEXT_PUBLIC_API_URL=http://localhost:8000
npm install
npm run dev
```

Open http://localhost:3000 and ask a question; the agent steps appear live. Run the backend commands from `backend/`: that is where `.env` is read from.

## Tests

None of the backend tests need the API, the worker or Redis running: the integration tests and LLM evals run the agent graph in-process, not through the queue.

| Tests | Needs running |
|---|---|
| Unit | Nothing (database, Redis and LLMs are mocked) |
| Integration | Postgres only, with an empty throwaway database (`apda_test`) |
| LLM evals | Postgres only (same test database), plus a real API key in `backend/.env` |
| Load (Locust) | The full stack, via `infra/docker-compose.loadtest.yml` |

The test database gets migrated and written to, so never point `TEST_DATABASE_URL` at your real `apda` database. Create it once, either in the Compose Postgres (first command below) or, on a native install, with `CREATE DATABASE apda_test OWNER apda;` (the `apda` user needs `CREATEROLE`, as in [Without Docker](#without-docker)).

From `backend/`, after `uv sync --extra dev`:

```bash
PYTHONPATH=. uv run pytest tests/unit                      # no DB, no LLM

docker compose -f ../infra/docker-compose.yml exec db createdb -U apda apda_test   # once
TEST_DATABASE_URL=postgresql+asyncpg://apda:apda@localhost:5432/apda_test \
  PYTHONPATH=. uv run pytest tests/integration             # real Postgres, scripted LLM

RUN_LLM_EVALS=1 TEST_DATABASE_URL=... PYTHONPATH=. \
  uv run pytest tests/integration/test_llm_evals.py -s     # real LLM (costs API calls)
```

Frontend: `npm test` (Vitest), `npm run lint` and `npm run build` in `frontend/`. CI runs all of this except the LLM evals (a manual workflow). Load test (Locust, mocked LLM): see `backend/tests/performance/locustfile.py`. Strategy and results: [TESTING.md](TESTING.md).

## Observability

Logs are the integration point: set `LOG_FORMAT=json` in `backend/.env` and every line from the API and the worker is one JSON object that Loki/Grafana, Datadog, ELK or CloudWatch can ingest as-is (`text`, the default, is for reading in a terminal). Every line carries `ts` (UTC), `level`, `logger`, `message`, and `run_id` while a question is being worked on, so one run can be followed end to end.

| `message` | Fields | Use |
|---|---|---|
| `http request` | `method`, `path`, `status`, `duration_ms`, `client` | request rate, errors, latency |
| `llm call` | `node_name`, `tier`, `provider`, `model`, `input_tokens`, `output_tokens`, `cached_input_tokens`, `latency_ms`, `outcome` | tokens per model, LLM latency, failed attempts |
| `agent step` | `node_name`, `step_type`, `content` | what each agent did |
| `run finished` | `status`, `duration_ms`, `llm_calls`, `errors`, `fallbacks` | run time, failure and fallback rates |

**Health:** `GET /api/health` says the API process is up; `GET /api/health/ready` checks Postgres, Redis and that a worker is running, and answers 503 naming what's down.

**LangSmith (optional):** the agents run on LangChain/LangGraph, so adding `LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY` and `LANGSMITH_PROJECT` to `backend/.env` traces every graph step and LLM call, with no code change. Note this sends prompts and data to LangSmith.

## Sample questions

| Question | Shows |
|---|---|
| How did retrenchment of residents and non-residents change since 2015? | Time range detected → one row per year → line chart |
| How did the share of women working 60+ hours change from 2023 to 2025? | A share with the right denominator, across 3 files merged into one view |
| Which university had the highest graduate employment rate in 2023? | Answered per university (averaged across degrees), not from one degree |
| Which MRT stations have the shortest travel time to junior colleges? | Long list: the 15 shortest charted, the full list in the Data tab |
| What was Singapore's GDP growth rate in 2020? | Honest refusal: no dataset covers it |

Each answer has four tabs: **Report** (chart and text), **Data** (the query result and its SQL), **Agent steps** (the full trace) and **Token usage** (per LLM call). History is in the left sidebar; charts export to PNG/PDF and data to CSV.

## Tech stack

| Area | Choice | Why |
|---|---|---|
| Frontend | Next.js, TypeScript, Recharts, CSS Modules | Modern standard, support hot-reload |
| Backend | FastAPI, SQLAlchemy async, Alembic, `uv` | Well supported, async-native |
| Database | PostgreSQL | Supports JSONB table + typed views generated per dataset |
| Queue | SAQ on Redis | Async-native; Redis Streams → SSE |
| Agents | LangGraph | Modern standard, facilitates ReAct flow |
| LLMs | OpenAI + AWS Bedrock behind one factory | Two clouds provider requirement |

## Repository

```
backend/    FastAPI app, agents (app/agents), data layer (app/data), tests
frontend/   Next.js app
infra/      Docker Compose
.github/    CI (lint, tests, build) and the manual LLM-eval workflow
```
