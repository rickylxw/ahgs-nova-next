# -*- coding: utf-8 -*-
"""应用工厂与生命周期。

单一模式(standalone):health + /api/v2/* + 官方兼容层,自持数据与执行。
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import __version__
from .arenas.base import ArenaError
from .context import AppContext
from .core import errors
from .core.config import get_settings
from .core.security import hash_password, now_utc
from .db.session import init_db
from .services.executors.abtest import AbTestExecutor
from .services.executors.arena_match import ArenaMatchExecutor
from .services.executors.evolve_engine import EvolveEngineExecutor
from .services.executors.grind import GrindExecutor
from .services.executors.mock_evolve import MockEvolveExecutor

log = logging.getLogger("nova")


def _register_executors(ctx: AppContext) -> None:
    orch = ctx.orchestrator
    orch.register_executor(MockEvolveExecutor())
    orch.register_executor(EvolveEngineExecutor())
    orch.register_executor(GrindExecutor())
    orch.register_executor(AbTestExecutor())
    orch.register_executor(ArenaMatchExecutor())


def _error_envelope(status: int, code: str, message: str,
                    retryable: bool = False, detail=None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"code": code, "message": message,
                 "retryable": retryable, "detail": detail},
    )


class SecurityHeadersMiddleware:
    """安全响应头(安全报告 §5-7)。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                existing = {k.lower() for k, _ in headers}
                additions = [
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'"),
                ]
                for k, v in additions:
                    if k not in existing:
                        headers.append((k, v))
            await send(message)

        await self.app(scope, receive, send_with_headers)


def create_app(settings=None) -> FastAPI:
    settings = settings or get_settings()
    ctx = AppContext.build(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await init_db(ctx.engine)
        await _ensure_admin(ctx)
        # 平台默认 key 池 → 注册 OpenAI 兼容适配器(键名即适配器名,降级链引用它)
        for name, conf in (settings.llm_platform_keys or {}).items():
            if isinstance(conf, dict) and conf.get("base_url"):
                ctx.llm.configure_openai_compat(
                    str(name), str(conf["base_url"]), str(conf.get("api_key") or ""))
        ctx.llm.set_fallback_chain(settings.llm_fallback_chain)
        ctx.arenas.load_plugins(settings.arena_plugins)
        _register_executors(ctx)
        await ctx.orchestrator.start()
        log.info("Nova Backend %s 启动: db=%s", __version__,
                 settings.database_url.split("://")[0])
        try:
            yield
        finally:
            await ctx.orchestrator.stop()
            await ctx.engine.dispose()

    app = FastAPI(
        title="Nova Backend",
        version=__version__,
        description="AHGS NOVA 自建后端(standalone:自持数据与执行)",
        lifespan=lifespan,
    )
    ctx.attach(app)

    # ---- 中间件 ----
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware, allow_origins=settings.cors_origins,
            allow_credentials=False,  # 安全报告 §5-6:不允许凭证 + 白名单
            allow_methods=["*"], allow_headers=["*"],
        )
    app.add_middleware(SecurityHeadersMiddleware)

    # ---- 错误处理(结构化信封) ----

    @app.exception_handler(errors.NovaError)
    async def _nova_error_handler(request: Request, exc: errors.NovaError):
        return _error_envelope(exc.status, exc.code, exc.message,
                               exc.retryable, exc.detail)

    @app.exception_handler(ArenaError)
    async def _arena_error_handler(request: Request, exc: ArenaError):
        status = 404 if exc.code == "ARENA_NOT_FOUND" else 400
        return _error_envelope(status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(request: Request, exc: RequestValidationError):
        return _error_envelope(422, "INVALID_INPUT", "请求参数校验失败",
                               detail=exc.errors()[:10])

    @app.exception_handler(Exception)
    async def _unhandled_handler(request: Request, exc: Exception):
        log.exception("未处理异常 %s %s", request.method, request.url.path)
        return _error_envelope(500, "INTERNAL_ERROR", "服务器内部错误")

    # ---- 路由(顺序即优先级:代理最后挂载) ----
    from .api.health import router as health_router
    from .api.v2.auth import router as v2_auth
    from .api.v2.runs import router as v2_runs
    from .api.v2.seeds import router as v2_seeds
    from .api.v2.datasets import router as v2_datasets
    from .api.v2.arena import router as v2_arena
    from .api.v2.events import router as v2_events
    from .api.v2.admin import router as v2_admin
    from .api.v2.prescreen import router as v2_prescreen

    app.include_router(health_router)
    app.include_router(v2_auth)
    app.include_router(v2_runs)
    app.include_router(v2_seeds)
    app.include_router(v2_datasets)
    app.include_router(v2_arena)
    app.include_router(v2_prescreen)
    app.include_router(v2_admin)
    app.include_router(v2_events)

    from .api.compat.auth import router as compat_auth
    from .api.compat.data import router as compat_data
    from .api.compat.evolution import router as compat_evolution
    from .api.compat.auth import router as compat_auth
    from .api.compat.data import router as compat_data
    from .api.compat.evolution import router as compat_evolution
    from .api.compat.developer import router as compat_developer
    from .api.compat.custom import router as compat_custom
    app.include_router(compat_auth)
    app.include_router(compat_data)
    app.include_router(compat_evolution)
    app.include_router(compat_developer)
    app.include_router(compat_custom)

    return app


async def _ensure_admin(ctx: AppContext) -> None:
    """按配置创建初始管理员(幂等)。"""
    s = ctx.settings
    if not s.admin_username or not s.admin_password:
        return
    from sqlalchemy import select
    from .db.models import User

    async with ctx.session_factory() as db:
        exists = (await db.scalars(
            select(User).where(User.username == s.admin_username))).first()
        if exists is None:
            db.add(User(username=s.admin_username, role="admin",
                        display_name=s.admin_display_name,
                        password_hash=hash_password(s.admin_password),
                        created_at=now_utc()))
            await db.commit()
            log.info("已创建管理员 %s", s.admin_username)


app = create_app()
