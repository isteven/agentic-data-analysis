from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import health, queries
from app.core.config import get_settings
from scripts.seed_datasets import main as seed_datasets

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
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
