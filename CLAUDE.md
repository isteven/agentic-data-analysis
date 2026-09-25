# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Agentic Policy Data Analytics Platform: a natural-language query interface over real
Singapore government datasets (data.gov.sg, MOM), answered via an LLM pipeline with a
Next.js frontend and FastAPI backend, deployed via Docker Compose.

**Read `ARCHITECTURE.md` and `DATA_SOURCES.md` before making non-trivial changes.**
`ARCHITECTURE.md` is the living design doc for the full target system (multi-agent
LangGraph pipeline, SAQ/Redis worker, multi-provider LLM abstraction, SSE trace
streaming, cost tracking, etc.) — it explains *why* things are shaped the way they are,
including rejected alternatives. See its §2 for a standing spec-vs-actual status
table per layer. `DATA_SOURCES.md` documents the dataset catalog, provenance, and known
data-quality quirks (sentinel values, sheet-naming drift, classification breaks) that the
seed script works around.

**Current implementation status: M1 is complete; M2 is in progress.** The real 5-node
LangGraph pipeline (coordinator → extraction → analytics → report_writer → validator) is
built and merged to `main`. Typed Postgres views over the stored dataset rows, shaped by
structure inferred at ingest, are built for the planned SQL planner; the query path still
uses the pandas analytics node. The live data.gov.sg API client exists but no current
dataset uses `mode: api`. Still outstanding from M2: the SAQ worker task exists
(`backend/app/worker.py`) but no route enqueues it yet — `/api/queries` still runs the
graph synchronously in-request; there is no SSE trace streaming yet (the frontend
fetches the trace once, after the run completes); Bedrock is stubbed, not live; no
cost/token tracking yet. Don't assume any component described in `ARCHITECTURE.md`
exists in code without checking; `git log` and the actual `backend/app/` tree are the
source of truth for what's built vs. planned. `solutioning.md` and
`project-management.md` (decision log and milestone tracker) are intentionally
gitignored and local-only to the author's machines — they will not exist in a fresh
clone.

## Commands

### Backend (`backend/`)

Dependency management is `uv`, not plain pip/poetry.

```
uv sync                                    # install deps into backend/.venv
uv run alembic upgrade head                # apply migrations
uv run python -m scripts.seed_datasets     # seed datasets (idempotent, content-hash based)
uv run uvicorn app.main:app --reload --port 8000
uv run ruff check .
uv run black .
```

The app's lifespan hook (`app/main.py`) runs Alembic migrations and the seed script
automatically on startup — the manual commands above are for running them standalone
(e.g. after schema/data changes) or when iterating outside the full app startup.

Unit tests live in `backend/tests/unit/` (no DB, no LLM). Install dev deps with
`uv sync --extra dev` (a plain `uv sync` drops pytest), then run
`PYTHONPATH=. uv run pytest tests/unit` from `backend/`. No integration tests yet.

### Frontend (`frontend/`)

```
npm install
npm run dev      # next dev
npm run build
npm run lint      # eslint
```

### Docker Compose (primary way to run the full stack)

```
cd infra
docker compose up --build
```

Brings up `db` (postgres:16), `redis` (redis:7, not yet wired into Compose as a worker
service — `backend/app/worker.py`'s SAQ task exists but nothing enqueues it yet),
`backend`, `frontend`. Requires
`backend/.env` and `frontend/.env` to exist first (copy from the `.env.example` in
each directory — **each service owns its own env file, there is no root `.env`**).

### Running without Docker

The current code path (sync FastAPI route running the LangGraph pipeline in-request, no
SAQ/Redis usage yet) only actually needs Postgres — not Redis — so it's runnable with a
native Postgres install:
`uv sync` → `uv run alembic upgrade head` → `uv run python -m scripts.seed_datasets` →
`uv run uvicorn app.main:app --port 8000`, plus `npm run dev` in `frontend/`. Point
`DATABASE_URL` in `backend/.env` at `localhost` instead of the Compose service name `db`.

## Architecture notes worth knowing before editing

- **Provider abstraction**: agent/service code must go through
  `get_chat_model()` in `backend/app/llm/provider_factory.py`, never import
  `langchain_openai`/`langchain_aws` directly — this is the single swap point for
  provider selection, tiering (`fast`/`quality`), and (eventually) fallback logic.
- **Dataset manifest**: `backend/data/manifest.yaml` is the catalog of every dataset —
  source, local file path, format, and `mode: file` vs `mode: api`. Each dataset
  declares its own extraction mode; this is a property of the dataset, not a per-query
  toggle (see `ARCHITECTURE.md` §4.5 for why).
- **Don't rely on hardcoded values or variables** as there can be more CSV files (or any other data format) with different structures. This is an agentic application and it should be dynamic enough to cater for various data structures.
- **Seed script** (`backend/scripts/seed_datasets.py`) parses each file, profiles it,
  stores its rows in `dataset_records` and rebuilds the typed views in the `data`
  schema. Which rows are totals, how values nest and which measures may be summed is
  inferred from the numbers (`app/data/structure.py`), not declared per dataset. It
  re-seeds when a file's content hash or `PROFILER_VERSION` changes, and prunes
  datasets removed from the manifest.
- **Incoming data is curated mock data**: files in `backend/data/incoming/` are
  derived from public downloads but edited (swapped, trimmed); don't treat drift from
  the published originals as a bug.
- **SQLAlchemy models use `sqlalchemy.dialects.postgresql.UUID` as the primary key type
  on every table** (`backend/app/models/*.py`), plus JSONB columns. This is
  Postgres-specific and deliberate — Postgres is the only supported database engine, by
  design, not as a gap to eventually fill. (`ARCHITECTURE.md` §5 previously floated a
  SQLite unit-test fallback; dropped — true unit tests mock the DB layer instead, and
  tests that need a real engine use real Postgres via CI service containers, so a second
  engine would only have duplicated that tier while catching fewer real bugs.)
- **Excel parsing** (`backend/app/data/parsers/excel_parser.py`) is hand-rolled against
  the MOM `F2` sheet's specific layout (fixed header row, sex/hours-bucket row
  structure, blank-row footer boundary) — it is not a general-purpose Excel reader, and
  assumes the exact sheet shape documented in `DATA_SOURCES.md`.
- **Env files are per-service, not shared**: `backend/.env` / `backend/.env.example`
  and `frontend/.env` / `frontend/.env.example` are separate, each read only by their
  own app. There is no root-level `.env`. `docker-compose.yml`'s `env_file` for each
  service points at that service's own file.

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

