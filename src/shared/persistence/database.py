from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.config import get_settings
from shared.persistence.models import Base


def _ensure_data_dir() -> None:
    db_url = get_settings().database_url
    if "sqlite" in db_url:
        path = db_url.split("///")[-1]
        Path(path).parent.mkdir(parents=True, exist_ok=True)


_engine = None
_session_factory = None


def get_engine():
    global _engine
    if _engine is None:
        _ensure_data_dir()
        _engine = create_async_engine(get_settings().database_url, echo=get_settings().debug)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


async def init_db() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
