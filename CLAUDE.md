# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Agentic Policy Data Analytics Platform: a natural-language query interface over real
Singapore government datasets (data.gov.sg, MOM), answered via an LLM pipeline with a
Next.js frontend and FastAPI backend, deployed via Docker Compose.

**Read `ARCHITECTURE.md` and `DATA_SOURCES.md` before making non-trivial changes.**
`ARCHITECTURE.md` is the living design doc for the full target system (multi-agent
LangGraph pipeline, arq/Redis worker, multi-provider LLM abstraction, WebSocket trace
streaming, cost tracking, etc.) — it explains *why* things are shaped the way they are,
including rejected alternatives. `DATA_SOURCES.md` documents the dataset catalog,
provenance, and known data-quality quirks (sentinel values, sheet-naming drift,
classification breaks) that the seed script works around.

**Current implementation status: only the M1 "walking skeleton" milestone is built.**
The backend today is a single synchronous FastAPI route that queries one seeded dataset
and calls an LLM directly — there is no LangGraph agent graph, no arq worker, no Redis
usage, and no WebSocket trace streaming yet, even though `ARCHITECTURE.md` describes
that full target design. Don't assume any component described in `ARCHITECTURE.md`
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

No `tests/` directory exists yet, despite `pyproject.toml` having pytest config
(`testpaths = ["tests"]`) — don't assume test infrastructure is in place.

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

Brings up `db` (postgres:16), `redis` (redis:7, currently unused by any code path —
reserved for the planned arq worker), `backend`, `frontend`. Requires
`backend/.env` and `frontend/.env` to exist first (copy from the `.env.example` in
each directory — **each service owns its own env file, there is no root `.env`**).

### Running without Docker

The current code path (single sync FastAPI route, no arq/Redis usage) only actually
needs Postgres — not Redis — so it's runnable with a native Postgres install:
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
- **Seed script** (`backend/scripts/seed_datasets.py`) is the only place `file`-mode
  datasets get parsed and cleaned — deterministic, hand-written rules per dataset
  (sentinel-value handling, MOM sheet footer/header skipping, a classification-era
  filter on the retrenchment series). It skips re-seeding a dataset whose source file
  content hash hasn't changed. Agents/routes read from Postgres, never re-parse raw
  files at query time.
- **SQLAlchemy models use `sqlalchemy.dialects.postgresql.UUID` as the primary key type
  on every table** (`backend/app/models/*.py`). This is Postgres-specific — switching to
  SQLite or another engine is not a config change, it requires touching every model to
  use a portable UUID type. Postgres is the only supported database engine right now,
  despite `ARCHITECTURE.md` §5 mentioning a SQLite test fallback as a future intent.
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

Note: WIP means the work on that commit is not yet done. 

