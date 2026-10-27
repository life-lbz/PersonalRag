"""数据库会话：FastAPI 用 async engine，Celery worker 用 sync engine（threads 池）。"""
from __future__ import annotations

from collections.abc import AsyncGenerator, Generator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

async_engine = create_async_engine(
    settings.postgres.dsn, pool_size=settings.postgres.pool_size, pool_pre_ping=True
)
AsyncSessionLocal = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

sync_engine = create_engine(
    settings.postgres.sync_dsn, pool_size=5, pool_pre_ping=True, pool_recycle=3600
)
SyncSessionLocal = sessionmaker(bind=sync_engine, class_=Session, expire_on_commit=False)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


def get_sync_session() -> Generator[Session, None, None]:
    """Celery 任务内使用（with 语句）。"""
    return SyncSessionLocal()
