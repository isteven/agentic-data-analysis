"""Integration tests: real Postgres, real seeded data, no network LLM.

Run with TEST_DATABASE_URL pointing at a throwaway database, e.g.
    TEST_DATABASE_URL=postgresql+asyncpg://apda:apda@localhost:5432/apda_test \
        PYTHONPATH=. uv run pytest tests/integration
Skipped when it's unset, so a plain `pytest` never touches a real database.
"""

import os
from pathlib import Path

import pytest
import pytest_asyncio

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
if TEST_DATABASE_URL:
    # Must happen before anything imports app.db.session, which builds its engine
    # from settings at import time.
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL

BACKEND_DIR = Path(__file__).resolve().parents[2]


def pytest_collection_modifyitems(config, items):
    if TEST_DATABASE_URL:
        return
    skip = pytest.mark.skip(reason="TEST_DATABASE_URL not set")
    for item in items:
        if "integration" in item.path.parts:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def migrated_db():
    """Schema at head. Sync on purpose: Alembic's env runs its own event loop."""
    from alembic import command
    from alembic.config import Config

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "app" / "db" / "migrations"))
    command.upgrade(config, "head")


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def seeded_db(migrated_db):
    """Every manifest dataset loaded from backend/data and the views rebuilt - the same
    path the app runs on startup. Idempotent, so a reused test database is fine."""
    from scripts.seed_datasets import main as seed

    await seed()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def catalog(seeded_db):
    from app.data.manifest import load_manifest
    from app.data.views import load_view_catalog
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        return await load_view_catalog(session, load_manifest())
