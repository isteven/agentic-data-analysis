# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Agentic Policy Data Analytics Platform: a natural-language query interface over Singapore
government datasets (data.gov.sg, MOM). A LangGraph multi-agent pipeline picks datasets,
has the database compute the numbers, writes a cited report and checks it. Next.js
frontend, FastAPI backend, SAQ worker on Redis, PostgreSQL, deployed with Docker Compose.

## Where to look first

- **`ARCHITECTURE.md`**: the design and the reasons behind it, including rejected
  alternatives. Read it before any
  non-trivial change, and update it in the same PR when a change alters the design.
- **`DATA_SOURCES.md`**: dataset catalog, provenance, known data quirks.
- **`TESTING.md`**: test layers, hallucination checks, results.
- **The code is the source of truth.** Don't assume something described in a doc exists
  without checking `backend/app/` and `git log`.
- `solutioning.md` (decision log) and `project-management.md` (progress tracker) are
  gitignored and local-only; they won't exist in a fresh clone.

## Commands

### Backend (`backend/`, managed with `uv`, not pip/poetry)

```
uv sync --extra dev                        # deps incl. pytest (a plain `uv sync` drops them)
uv run alembic upgrade head                # migrations (also run on app startup)
uv run python -m scripts.seed_datasets     # seed datasets (also run on app startup)
uv run uvicorn app.main:app --reload --port 8000
uv run ruff check .                        # enforced in CI
uv run black .
PYTHONPATH=. uv run pytest tests/unit      # no DB, no LLM

# Integration tests: real Postgres (e.g. the Compose db), throwaway database
TEST_DATABASE_URL=postgresql+asyncpg://apda:apda@localhost:5432/apda_test   PYTHONPATH=. uv run pytest tests/integration

# LLM evals: real models, costs API calls; run only when asked
RUN_LLM_EVALS=1 TEST_DATABASE_URL=... PYTHONPATH=.   uv run pytest tests/integration/test_llm_evals.py -s
```

The seed re-runs only when a file's content hash or `PROFILER_VERSION` changes, and
prunes datasets removed from the manifest.

### Frontend (`frontend/`)

```
npm install
npm run dev
npm test          # Vitest
npm run lint
npm run build
npx tsc --noEmit  # typecheck (CI runs it)
```

Change `package-lock.json` only with npm 10 (e.g. in `node:20-slim`); npm 11 prunes
optional packages and breaks `npm ci` in CI.

### Docker Compose (the primary way to run the stack)

```
cd infra
docker compose up --build                                                     # db, redis, backend, worker, frontend
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build     # frontend hot reload
docker compose -f docker-compose.yml -f docker-compose.loadtest.yml up        # mock LLM + apda_load DB, for Locust
```

Needs `backend/.env` and `frontend/.env` (copy each from its `.env.example`). **Each
service owns its own env file; there is no root `.env`.** Health: `GET /api/health`
(liveness), `GET /api/health/ready` (Postgres, Redis, worker).

Without Docker: native Postgres and Redis, then from `backend/` run the API (`uvicorn`
above) and the worker (`uv run python -m saq app.worker.settings_dict`), plus
`npm run dev` in `frontend/`. Point `DATABASE_URL` and `REDIS_URL` in `backend/.env` at
`localhost` instead of the Compose service names.

## Rules for changing code

### Agents and LLMs
- **Get models only through `get_chat_model()`** (`app/llm/provider_factory.py`), via
  `node_model(state, node, tier)` in agent nodes. Never import `langchain_openai` /
  `langchain_aws` elsewhere: the factory is where provider choice, tiering and fallback
  (with token tracking) happen.
- **The database computes every number; an LLM never does.** LLMs interpret the
  question, choose what to compute and judge the result. Don't add a step where an LLM
  produces or re-types data values.
- **LLM-written SQL goes through the gate and the read-only runner**
  (`app/data/sql_gate.py`, `sql_runner.py`). Don't bypass or loosen either; each layer
  alone must stop a write.
- **Every node reports what it does with `emit_trace()`** (reasoning / action /
  observation); the trace is the user-facing record of the agents' reasoning.
- **A failing step must not kill the run.** Record the error, trace it and let the run
  finish as `partial` with an honest explanation.

### Data
- **No hardcoded column names, values or per-dataset rules.** New files with other
  structures must work unchanged. Use the profile made at ingest (column roles: time /
  dimension / measure; `app/data/profiler.py`) and the structure inferred from the
  numbers (`app/data/structure.py`).
- **Data rules live in the views, not the prompt.** If totals, overlaps or non-additive
  measures cause wrong answers, fix the view shape; prompt instructions alone proved
  unreliable.
- **Files in `backend/data/incoming/` are curated mock data** (edited from public
  downloads). Drift from the published originals is not a bug.
- The Excel parser is built for the MOM `F2` sheet layout only; it isn't a general
  Excel reader.
- `backend/data/manifest.yaml` catalogs datasets (metadata only). `mode: file | api` is
  a property of each dataset, not a per-query switch.

### Backend
- **PostgreSQL only, by design** (Postgres `UUID` keys, JSONB). Unit tests mock the
  database; tests that need a real engine use real Postgres. Don't add a second engine.
- Schema changes go through a new Alembic migration in `app/db/migrations/versions/`.
- Keep database sessions short: open one per read or write, never across an LLM call.
- Slow work belongs in the worker, not the API process. The API accepts, relays and
  serves; `POST /api/queries` only enqueues.
- Logs: use the module logger; lines logged during a run carry its `run_id`
  automatically. Put details in `extra={...}` fields so JSON logs (`LOG_FORMAT=json`)
  stay queryable.

### Frontend
- Plain `fetch` in effects, cancelled on cleanup (`AbortController`); no data-fetching
  or global state library unless a concrete need appears.
- Styles are CSS Modules; colours are theme tokens in `app/globals.css` (light and
  dark), including `--chart-*` for charts.
- Display rules come from the API (e.g. `analysis.time_columns`, chart spec), not from
  column names in the frontend.

### Testing and verification
- **Tests first**, and confirm they fail before the change. Test behaviour, not
  implementation; every test asserts something.
- Before calling a change done: `ruff check` and backend unit tests; integration tests
  when touching persistence, the graph or SQL; frontend `npm test`, lint, typecheck.
- For changes to agents, prompts or data handling, also run a real question through the
  running stack and check the report, the data and the trace, not only the tests.

## Branching Strategy

use **trunk-based development** for a solo-developer. Feature flag is not required.

Branch name should follow **conventional branch**. List of conventional branch names:
- feat/xxxxx for new features
- fix/xxxxx for repairs/bugfix
- chore/xxxxx for maintenance or documentation.

Example of valid branch names: 
- feat/add-login-page
- fix/PROJ-123-fix-header-bug
- chore/update-dependencies

## Commit

Commit message should follow **conventional commit**. Format:

type(scope): description

Type must be one of the following:

| Type         | Description                                                                                         |
| ------------ | --------------------------------------------------------------------------------------------------- |
| **build**    | Changes that affect the build system or external dependencies (example scopes: gulp, broccoli, npm) |
| **chore**    | Changes that don't modify src or test files (e.g. updating `.gitignore`, repo housekeeping)          |
| **ci**       | Changes to our CI configuration files and scripts (examples: GitHub Actions)                        |
| **docs**     | Documentation only changes                                                                          |
| **feat**     | A new feature                                                                                       |
| **fix**      | A bug fix                                                                                           |
| **refactor** | A code change that neither fixes a bug nor adds a feature                                           |
| **test**     | Adding missing tests or correcting existing tests                                                   |

**Scope** is the affected part, or where the majority of work happens. Make it one word only. It's not compulsory but best if you can include it.

Examples:
- feat(login): add username textfield
- feat(user): WIP: add pagination on the user listing
- fix(product): fix delete product bug
- build(npm): add test coverage in npm script
- refactor(search): break down search functionality into several functions
- test(product): add more unit test for some specific products  
- docs(contact): add documentation about contact page logic
- ci(github): add new environment variable
- chore(repo): add gitignore for env files and build artifacts

Note: 
1. WIP in the commit message means the work on that commit is not yet done. 
2. Prevent PRs that are too big. Like, 10 commmits or more in a single PR is definitely too big. Try to break it down.

