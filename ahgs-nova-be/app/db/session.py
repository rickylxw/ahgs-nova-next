# -*- coding: utf-8 -*-
"""异步引擎与会话工厂。SQLite/Postgres 双支持,由 settings.database_url 决定。"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine,
)

from ..core.config import Settings
from .base import Base
from . import models  # noqa: F401  确保模型注册


def make_engine(settings: Settings) -> AsyncEngine:
    kwargs: dict = {"echo": False}
    if settings.database_url.startswith("sqlite"):
        # 内存库(测试)需 StaticPool 共享连接;文件库默认并发即可
        if ":memory:" in settings.database_url or settings.database_url.endswith(":///:memory:"):
            from sqlalchemy.pool import StaticPool
            kwargs["poolclass"] = StaticPool
            kwargs["connect_args"] = {"check_same_thread": False}
        engine = create_async_engine(settings.database_url, **kwargs)

        # WAL:读写不互斥;busy_timeout:写锁等待上限。
        # (不用 BEGIN IMMEDIATE:那会让所有读事务也抢写锁,高并发下适得其反)
        from sqlalchemy import event

        @event.listens_for(engine.sync_engine, "connect")
        def _sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=10000")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
        return engine
    return create_async_engine(settings.database_url, **kwargs)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_db(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
