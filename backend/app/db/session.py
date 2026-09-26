from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

settings = get_settings()

engine = create_async_engine(settings.database_url, echo=False, future=True)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

# What long-running work (the agent graph, the worker) is given instead of a session: it
# opens a short session per unit of database work, so no transaction stays open across
# LLM calls that can take minutes.
SessionFactory = async_sessionmaker[AsyncSession]


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
