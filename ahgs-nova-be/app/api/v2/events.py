# -*- coding: utf-8 -*-
"""WebSocket 实时推送(计划痛点 #10:替代 45s 轮询)。

- /api/v2/ws/runs/{run_id}?token=JWT  单运行频道(每代结束推 generation_end 全量);
- /api/v2/ws?token=JWT                全局频道(管理员,监控页)。
断线重连:重连后先收 hello(含当前状态),再续收事件。
"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Query, Request, WebSocket, WebSocketDisconnect

from ...core import errors
from ...core.security import decode_access_token
from ...db.models import Run

router = APIRouter(tags=["v2-ws"])


def _token_of(ws: WebSocket, token: str | None) -> dict:
    ctx = ws.app.state.ctx
    if not token:
        raise errors.auth_required()
    return decode_access_token(token, ctx.settings.jwt_secret)


async def _relay(ws: WebSocket, run_id: str | None) -> None:
    ctx = ws.app.state.ctx
    key = run_id if run_id is not None else "*"
    q = ctx.bus.subscribe(key)
    try:
        while True:
            event = await q.get()
            await ws.send_text(json.dumps(event, ensure_ascii=False))
    finally:
        ctx.bus.unsubscribe(key, q)


async def _recv_close(ws: WebSocket) -> None:
    try:
        while True:
            msg = await ws.receive_text()
            if msg == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        pass


@router.websocket("/api/v2/ws/runs/{run_id}")
async def ws_run(ws: WebSocket, run_id: int, token: str | None = Query(default=None)):
    await ws.accept()
    ctx = ws.app.state.ctx
    try:
        payload = _token_of(ws, token)
        async with ctx.session_factory() as db:
            run = await db.get(Run, run_id)
            if run is None:
                await ws.close(code=4404)
                return
            if run.user_id != int(payload["sub"]) and payload.get("role") != "admin":
                await ws.close(code=4403)
                return
            hello = {"type": "hello", "run_id": run.id, "data": {
                "status": run.status, "current_generation": run.current_generation,
                "total_generations": run.total_generations,
                "best_objective": run.best_objective,
            }}
        await ws.send_text(json.dumps(hello, ensure_ascii=False))
        await asyncio.gather(_relay(ws, str(run_id)), _recv_close(ws))
    except WebSocketDisconnect:
        pass
    except errors.NovaError:
        await ws.close(code=4401)


@router.websocket("/api/v2/ws")
async def ws_all(ws: WebSocket, token: str | None = Query(default=None)):
    await ws.accept()
    try:
        payload = _token_of(ws, token)
        if payload.get("role") != "admin":
            await ws.close(code=4403)
            return
        await ws.send_text(json.dumps({"type": "hello", "data": {"scope": "*"}}))
        await asyncio.gather(_relay(ws, None), _recv_close(ws))
    except WebSocketDisconnect:
        pass
    except errors.NovaError:
        await ws.close(code=4401)
