# -*- coding: utf-8 -*-
"""v2 预筛端点(计划 §4.3):把冲榜工作流验证过的 prescreen 机制产品化。

合成迷你实例 + 子进程限时:崩溃/非法/超时候选在进主评估前淘汰,
返回结构化 fail_reason(而非 detail 字符串)。
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from ...core import errors
from ...db.models import Problem
from ...schemas import PrescreenIn
from ...services.evaluators import evaluate_candidate
from ..deps import DbDep, UserDep

router = APIRouter(tags=["v2-prescreen"])


@router.post("/api/v2/prescreen")
async def prescreen(body: PrescreenIn, request: Request, db: DbDep, user: UserDep):
    problem = await db.get(Problem, body.problem_key)
    if problem is None:
        raise errors.not_found("题目", body.problem_key)
    if body.timeout_seconds > 60:
        raise errors.invalid_input("timeout_seconds 上限 60s")

    contract = problem.contract or {}
    spec = contract.get("evaluate") or {}
    config = {"ascend": problem.ascend, **contract.get("evaluate_config", {})}

    if spec.get("judge"):
        # 裁判驱动协议:迷你实例上由 judge 流式驱动候选
        from ...services.evaluators import evaluate_solution

        instance = body.instance or spec.get("prescreen_instance") \
            or spec.get("instance") or {}
        outcome = await evaluate_solution(
            body.candidate_code, judge_source=spec["judge"],
            judge_entry=spec.get("judge_entry", "judge"),
            entry=spec.get("entry"), instance=instance, config=config,
            timeout=body.timeout_seconds)
    else:
        # 通用契约:候选自带 entry(instance, config) -> objective
        from ...services.evaluators import evaluate_candidate

        entry = contract.get("evaluate_entry", "evaluate")
        instance = body.instance or (contract.get("prescreen_instance") or {})
        outcome = await evaluate_candidate(
            body.candidate_code, entry=entry, instance=instance,
            config=config, timeout=body.timeout_seconds)

    d = outcome.as_dict()
    d["problem_key"] = problem.key
    d["ascend"] = problem.ascend
    return d
