import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import health, queries
from app.core.config import get_settings
from scripts.seed_datasets import main as seed_datasets

settings = get_settings()

BACKEND_ROOT = Path(__file__).resolve().parent.parent


def _run_migrations() -> None:
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "app" / "db" / "migrations"))
    command.upgrade(cfg, "head")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await anyio.to_thread.run_sync(_run_migrations)
    await seed_datasets()
    yield


app = FastAPI(title="Agentic Policy Data Analytics Platform", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.cors_origin],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

app.include_router(health.router)
app.include_router(queries.router)
