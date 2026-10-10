# -*- coding: utf-8 -*-
"""应用上下文:单例服务的容器(lifespan 构建,app.state 持有)。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from .core.config import Settings
from .core.ratelimit import RateLimiter
from .db.session import make_engine, make_session_factory
from .arenas import ArenaRegistry, default_registry
from .services.events import EventBus
from .services.llm import LLMGateway
from .services.orchestrator import Orchestrator
from .services.queue import MemoryQueue
from .services.storage import LocalStorage


@dataclass
class AppContext:
    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker
    bus: EventBus
    queue: MemoryQueue
    orchestrator: Orchestrator
    storage: LocalStorage
    llm: LLMGateway
    limiter: RateLimiter
    arenas: ArenaRegistry
    extras: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def build(cls, settings: Settings) -> "AppContext":
        engine = make_engine(settings)
        session_factory = make_session_factory(engine)
        bus = EventBus()
        queue = MemoryQueue()
        storage = LocalStorage(settings.storage_dir)
        llm = LLMGateway()
        limiter = RateLimiter(max_failures=settings.login_max_failures,
                              lockout_seconds=settings.lockout_minutes * 60)
        orchestrator = Orchestrator(settings, session_factory, bus, queue,
                                    storage=storage, llm_gateway=llm)
        return cls(
            settings=settings, engine=engine, session_factory=session_factory,
            bus=bus, queue=queue, orchestrator=orchestrator, storage=storage,
            llm=llm, limiter=limiter, arenas=default_registry,
        )

    def attach(self, app: FastAPI) -> None:
        app.state.ctx = self


def ctx_of(request_or_app) -> AppContext:
    app = request_or_app.app if hasattr(request_or_app, "app") else request_or_app
    return app.state.ctx
