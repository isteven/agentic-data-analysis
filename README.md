# Agentic Policy Data Analytics

Ask a question about Singapore government statistics in plain English; a team of LLM agents picks the datasets, has the database compute the answer, writes a cited report with a chart, and checks it before you see it. Every step is shown live.

- **Data:** 6 files from data.gov.sg (CSV) and MOM (Excel), loaded into PostgreSQL. See [DATA_SOURCES.md](DATA_SOURCES.md).
- **Numbers come from the database, never the LLM.** Agents write SQL; the SQL is checked, then run read-only. Every number in the report is verified against the query result.
- **Two LLM providers** (OpenAI, AWS Bedrock) with automatic per-call fallback.

## How it works

```
Browser (Next.js) ──POST /api/queries──▶ FastAPI ──enqueue──▶ SAQ worker (Redis)
      ▲                                                            │
      └──────── live agent steps (SSE) ◀── Redis Stream ◀──────────┤
                                                                   ▼
   intent → coordinator → extraction → analytics (ReAct SQL) → report_writer → validator → reviewer
                                              ▲                                               │
                                              └─────────── sent back on a wrong answer ───────┘
```

| Agent | Job |
|---|---|
| intent | Restates the question precisely; declines what no dataset covers |
| coordinator | Picks the relevant datasets |
| extraction | Maps them to typed views; reports data-quality facts |
| analytics | ReAct loop: explores the views, writes SQL, fixes rejected queries |
| report_writer | Writes the report from the query result only |
| validator | Checks every number in the report against the result (code, no LLM) |
| reviewer | Judges whether the answer fits the question; sends it back once if not |

Design, trade-offs and rejected alternatives: [ARCHITECTURE.md](ARCHITECTURE.md).

## Run it (Docker Compose)

Requirements: Docker, an OpenAI API key.

```bash
cp backend/.env.example backend/.env      # set OPENAI_API_KEY
cp frontend/.env.example frontend/.env
cd infra
docker compose up --build
```

Open http://localhost:3000. Startup migrates the database and loads the datasets automatically. Services: `db` (Postgres 16), `redis`, `backend` (:8000), `worker`, `frontend` (:3000).

- **Bedrock (optional):** set `LLM_ENABLE_BEDROCK=true`, AWS credentials and `BEDROCK_MODEL_ID_*` in `backend/.env`. Pick the provider per question in the UI; if one fails, the call retries on the other.
- **Frontend hot reload:** `docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build`

## Tests

From `backend/`, after `uv sync --extra dev`:

```bash
PYTHONPATH=. uv run pytest tests/unit                      # no DB, no LLM

docker compose -f ../infra/docker-compose.yml exec db createdb -U apda apda_test   # once
TEST_DATABASE_URL=postgresql+asyncpg://apda:apda@localhost:5432/apda_test \
  PYTHONPATH=. uv run pytest tests/integration             # real Postgres, scripted LLM

RUN_LLM_EVALS=1 TEST_DATABASE_URL=... PYTHONPATH=. \
  uv run pytest tests/integration/test_llm_evals.py -s     # real LLM (costs API calls)
```

Frontend: `npm run lint` and `npm run build` in `frontend/`. CI runs all of this except the LLM evals (a manual workflow). Load test (Locust, mocked LLM): see `backend/tests/performance/locustfile.py`. Strategy and results: [TESTING.md](TESTING.md).

## Sample questions

| Question | Shows |
|---|---|
| How did retrenchment of residents and non-residents change since 2015? | Time range detected → one row per year → line chart |
| How did the share of women working 60+ hours change from 2023 to 2025? | A share with the right denominator, across 3 files merged into one view |
| Which university had the highest graduate employment rate in 2023? | Answered per university (averaged across degrees), not from one degree |
| Which MRT stations have the shortest travel time to junior colleges? | Long list: the 15 shortest charted, the full list in the Data tab |
| What was Singapore's GDP growth rate in 2020? | Honest refusal: no dataset covers it |

Each answer has four tabs: **Report** (chart and text), **Data** (the query result and its SQL), **Agent steps** (the full trace) and **Token usage** (per LLM call). History is in the left sidebar; charts export to PNG/PDF and data to CSV.

## Tech choices

| Area | Choice | Why |
|---|---|---|
| Agents | LangGraph | Loops (SQL retry, reviewer re-route) need conditional edges; state is inspectable at every step |
| Computation | LLM-written SQL on Postgres views, checked by `sqlglot`, run read-only | SQL is standard and LLMs write it well; the checks and a read-only role keep it safe |
| Data | One JSONB table + typed views generated per dataset | New files need no new tables; totals and hierarchies are inferred from the numbers |
| Queue / live trace | SAQ on Redis, Redis Streams → SSE | Async-native; a late subscriber replays the trace from the start |
| LLMs | OpenAI + AWS Bedrock behind one factory | Two clouds; per-call fallback that is visible in the trace |
| Frontend | Next.js, TypeScript, Recharts, CSS Modules | Charts drawn from backend specs; one CSS file per component |
| Backend | FastAPI, SQLAlchemy async, Alembic, `uv` | Async end to end; typed settings and migrations |

## Repository

```
backend/    FastAPI app, agents (app/agents), data layer (app/data), tests
frontend/   Next.js app
infra/      Docker Compose
.github/    CI (lint, tests, build) and the manual LLM-eval workflow
```
