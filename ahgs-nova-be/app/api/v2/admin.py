# -*- coding: utf-8 -*-
"""v2 管理端点:队列暂停(显式"数据保护中")、审计日志、LLM 网关运营视图。"""
from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import select

from ...core import errors
from ...core.audit import audit
from ...core.security import now_utc
from ...db.models import AuditLog, LlmCall
from ...schemas import QueuePauseIn
from ...services.llm import LLMError, LLMRequest
from ..deps import AdminDep, CtxDep, DbDep

router = APIRouter(prefix="/api/v2/admin", tags=["v2-admin"])


@router.put("/problems/{key}")
async def upsert_problem(key: str, request: Request, db: DbDep, admin: AdminDep):
    """创建/更新题目(题目注册中心的管理入口)。

    body: {name, kind=optimization|game|…, ascend=True, contract={}, dataset_version?}
    kind 决定允许的运行负载与榜单语义(见 /api/v2/meta/problem-kinds)。
    """
    from ...db.models import Problem
    from ...services.registry import get_problem_kind

    body = await request.json()
    kind = body.get("kind") or "optimization"
    if get_problem_kind(kind) is None:
        from ...services.registry import list_problem_kinds
        raise errors.invalid_input(
            f"未知题目类型: {kind}",
            detail={"known": [k["key"] for k in list_problem_kinds()]})
    problem = await db.get(Problem, key)
    if problem is None:
        problem = Problem(key=key, created_at=now_utc())
        db.add(problem)
    problem.name = body.get("name") or key
    problem.kind = kind
    problem.ascend = bool(body.get("ascend", True))
    if "contract" in body:
        problem.contract = body["contract"]
    if "dataset_version" in body:
        problem.dataset_version = body["dataset_version"]
    await audit(db, actor=admin.username, action="admin.problem_upsert",
                target=f"problem:{key}", detail={"kind": kind, "ascend": problem.ascend})
    await db.commit()
    return {"key": problem.key, "name": problem.name, "kind": problem.kind,
            "ascend": problem.ascend, "contract": problem.contract}


@router.post("/queue/pause")
async def set_queue_pause(body: QueuePauseIn, request: Request,
                          db: DbDep, admin: AdminDep):
    """显式暂停/恢复全局队列(原因+预告恢复时间,计划 §4.2)。"""
    ctx: CtxDep = request.app.state.ctx
    ctx.settings.queue_paused = body.paused
    ctx.settings.queue_pause_reason = body.reason
    ctx.settings.queue_pause_until = body.resume_at
    await audit(db, actor=admin.username, action="admin.queue_pause",
                detail={"paused": body.paused, "reason": body.reason,
                        "resume_at": body.resume_at})
    await db.commit()
    return {"paused": body.paused, "reason": body.reason,
            "resume_at": body.resume_at}


@router.get("/audit")
async def list_audit(db: DbDep, admin: AdminDep, limit: int = 100):
    rows = (await db.scalars(
        select(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 1000))
    )).all()
    return {"audit": [
        {"id": a.id, "actor": a.actor, "action": a.action, "target": a.target,
         "detail": a.detail,
         "created_at": a.created_at.isoformat() if a.created_at else None}
        for a in rows
    ]}


@router.get("/llm/providers")
async def llm_providers(ctx: CtxDep, admin: AdminDep):
    return {"providers": ctx.llm.list_providers(),
            "fallback_chain": [f"{a}:{m}" for a, m in ctx.llm.fallback_chain]}


@router.post("/llm/chat")
async def llm_chat(request: Request, db: DbDep, admin: AdminDep):
    """网关自测调用(管理端点;用户侧调用未来经配额开放)。

    body: {messages, model?, thinking?, timeout?, provider?}
    provider 非空时锁定该适配器单测(不经降级链);否则走默认降级链。
    """
    ctx: CtxDep = request.app.state.ctx
    body = await request.json()
    provider = str(body.get("provider") or "").strip()
    model = str(body.get("model") or "mock")
    try:
        resp = await ctx.llm.chat(
            LLMRequest(
                messages=body.get("messages") or [],
                model=model,
                thinking=body.get("thinking") or "default",
                timeout=float(body.get("timeout") or 60),
            ),
            user_id=admin.id, db=db,
            chain=[(provider, model)] if provider else None,
        )
    except LLMError as e:
        raise errors.NovaError(e.code, e.message, 502, retryable=e.retryable)
    await db.commit()
    return {"text": resp.text, "prompt_tokens": resp.prompt_tokens,
            "completion_tokens": resp.completion_tokens,
            "latency_ms": resp.latency_ms, "provider": resp.provider,
            "model": resp.model}


@router.get("/llm/calls")
async def llm_calls(db: DbDep, admin: AdminDep, limit: int = 100):
    rows = (await db.scalars(
        select(LlmCall).order_by(LlmCall.id.desc()).limit(min(limit, 1000))
    )).all()
    return {"calls": [
        {"id": c.id, "run_id": c.run_id, "user_id": c.user_id,
         "provider": c.provider, "model": c.model, "thinking": c.thinking,
         "prompt_tokens": c.prompt_tokens,
         "completion_tokens": c.completion_tokens,
         "latency_ms": c.latency_ms, "ok": c.ok, "error_code": c.error_code,
         "created_at": c.created_at.isoformat() if c.created_at else None}
        for c in rows
    ]}


@router.post("/arenas/reload-plugins")
async def reload_arena_plugins(request: Request, db: DbDep, admin: AdminDep):
    """重新加载 NOVA_ARENA_PLUGINS 外部对战游戏插件。"""
    ctx: CtxDep = request.app.state.ctx
    loaded = ctx.arenas.load_plugins(ctx.settings.arena_plugins)
    await audit(db, actor=admin.username, action="admin.arena_reload",
                detail={"loaded": loaded})
    await db.commit()
    return {"loaded": loaded, "arenas": ctx.arenas.list()}
