# -*- coding: utf-8 -*-
"""健康检查与元信息。"""
from __future__ import annotations

from fastapi import APIRouter, Request

from .. import __version__
from ..services.registry import list_problem_kinds

router = APIRouter(tags=["meta"])


@router.get("/api/health")
async def health(request: Request):
    ctx = request.app.state.ctx
    return {
        "ok": True,
        "service": "ahgs-nova-be",
        "version": __version__,
        "queue": {"paused": ctx.settings.queue_paused,
                  "reason": ctx.settings.queue_pause_reason,
                  "resume_at": ctx.settings.queue_pause_until,
                  "depth": ctx.queue.depth},
        "runs_active": ctx.orchestrator.active_count(),
    }


@router.get("/api/v2/meta/problem-kinds")
async def problem_kinds():
    """题目类型注册表(扩展点自省)。"""
    return {"kinds": list_problem_kinds()}
