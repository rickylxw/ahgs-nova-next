# -*- coding: utf-8 -*-
"""兼容层:/api/developer/*(官方开发者路由)。

- validate:框架源码语法校验(compile);
- upload:源码入对象存储,返回 framework_id(内容哈希派生,内容寻址幂等);
- run:与 /api/evolution/start 同一启动管线(framework_id 反查源码作为种子)。
"""
from __future__ import annotations

import hashlib

from fastapi import APIRouter, Request

from ...core import errors
from ..deps import DbDep, UserDep
from .evolution import _enqueue_evolution

router = APIRouter(tags=["compat-developer"])


def _framework_id(code: str) -> int:
    return int(hashlib.sha256(code.encode()).hexdigest()[:12], 16)


def _framework_key(fid: int) -> str:
    return f"frameworks/{fid}.py"


async def _load_framework(ctx, fid: int) -> str:
    key = _framework_key(fid)
    if not ctx.storage.exists(key):
        raise errors.not_found("框架", fid)
    return ctx.storage.get(key).decode("utf-8")


@router.post("/api/developer/validate")
async def developer_validate(request: Request, user: UserDep):
    body = await request.json()
    code = str(body.get("framework_code") or "")
    if not code.strip():
        raise errors.invalid_input("framework_code 为空")
    try:
        compile(code, "framework.py", "exec")
    except SyntaxError as e:
        return {"valid": False, "ok": False,
                "detail": f"语法错误(第 {e.lineno} 行): {e.msg}"}
    return {"valid": True, "ok": True, "detail": "校验通过"}


@router.post("/api/developer/upload")
async def developer_upload(request: Request, user: UserDep):
    ctx = request.app.state.ctx
    body = await request.json()
    code = str(body.get("framework_code") or "")
    if not code.strip():
        raise errors.invalid_input("framework_code 为空")
    fid = _framework_id(code)
    ctx.storage.put(_framework_key(fid), code.encode("utf-8"))
    return {"framework_id": fid,
            "framework_filename": body.get("framework_filename") or "framework.py"}


@router.post("/api/developer/run")
async def developer_run(request: Request, db: DbDep, user: UserDep):
    ctx = request.app.state.ctx
    body = await request.json()
    problem_key = body.get("problem_key")
    if not problem_key:
        raise errors.invalid_input("缺少 problem_key")

    code = str(body.get("framework_code") or "")
    if not code and body.get("framework_id") is not None:
        code = await _load_framework(ctx, int(body["framework_id"]))

    payload = dict(body)
    payload["framework_code"] = code or None
    run = await _enqueue_evolution(db, ctx, user, payload)
    return {"run_id": run.id}
