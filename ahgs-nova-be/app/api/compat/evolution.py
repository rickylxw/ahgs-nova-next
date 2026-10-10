# -*- coding: utf-8 -*-
"""兼容层:/api/evolution/* 与 /api/instances(映射到本地编排器)。

官方契约保持:POST /api/evolution/start → {run_id};
status/results/population 字段与官方同形;action 端点支持 stop/submit。
契约带 evaluate 规格的题目自动走本地进化引擎,其余由演示执行器承担。
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import select

from ...core import errors
from ...core.audit import audit
from ...core.security import now_utc
from ...db.models import Generation, Problem, Run, Submission
from ...schemas import CompatEvolutionStartIn
from ..deps import DbDep, UserDep
from ..v2.runs import resolve_default_kind, run_dict

router = APIRouter(tags=["compat-evolution"])


async def _enqueue_evolution(db, ctx, user, payload: dict) -> Run:
    """从官方形载荷发起进化(evolution/start 与 developer/run 共用)。"""
    problem_key = payload.get("problem_key")
    problem = await db.get(Problem, problem_key)
    if problem is None:
        raise errors.not_found("题目", problem_key)

    kind = resolve_default_kind(problem)
    config = {
        "num_generations": int(payload.get("num_generations") or 5),
        "population_size": payload.get("population_size"),
        "candidates_per_gen": payload.get("candidates_per_gen"),
        "llm_model": payload.get("llm_model"),
        "llm_thinking": payload.get("llm_thinking"),
        "llm_provider": payload.get("llm_provider"),
        "seed_code": payload.get("framework_code") or None,
        "ascend": bool(payload.get("ascend", problem.ascend)),
        "llm_base_url": payload.get("llm_base_url"),
        "use_local_llm": payload.get("use_local_llm", True),
        "framework_filename": payload.get("framework_filename") or "framework.py",
        "framework_type": payload.get("framework_type"),
        "fun_name": payload.get("fun_name"),
        "fun_args": payload.get("fun_args"),
        "fun_return": payload.get("fun_return"),
        "fun_notes": payload.get("fun_notes"),
        "problem_path": payload.get("problem_path"),
        "train_data": payload.get("train_data"),
        "train_solution": payload.get("train_solution"),
        "compat": True,
    }
    run = await ctx.orchestrator.enqueue_run(
        db, user_id=user.id, kind=kind, problem_key=problem_key,
        problem_kind=problem.kind, config=config,
        total_generations=int(payload.get("num_generations") or 5),
    )
    await audit(db, actor=user.username, action="evolution.start",
                target=f"run:{run.id}", detail={"via": "compat"})
    await db.commit()
    return run


@router.post("/api/evolution/start", status_code=200)
async def evolution_start(body: CompatEvolutionStartIn, request: Request,
                          db: DbDep, user: UserDep):
    ctx = request.app.state.ctx
    payload = {"problem_key": body.problem_key,
               "num_generations": body.num_generations,
               "framework_code": body.framework_code,
               "ascend": body.ascend,
               "llm_model": body.llm_model,
               "llm_base_url": body.llm_base_url,
               "use_local_llm": body.use_local_llm,
               "framework_filename": body.framework_filename,
               "framework_type": body.framework_type,
               "fun_name": body.fun_name, "fun_args": body.fun_args,
               "fun_return": body.fun_return, "fun_notes": body.fun_notes,
               "problem_path": body.problem_path,
               "train_data": body.train_data,
               "train_solution": body.train_solution,
               **(body.model_extra or {})}
    run = await _enqueue_evolution(db, ctx, user, payload)
    return {"run_id": run.id}


@router.get("/api/evolution/my")
async def evolution_my(db: DbDep, user: UserDep, limit: int = 50):
    rows = (await db.scalars(
        select(Run).where(
            Run.user_id == user.id,
            Run.kind.in_(("evolve_local", "evolve_official", "evolve_llm")))
        .order_by(Run.id.desc()).limit(min(limit, 200)))).all()
    return {"runs": [run_dict(r) for r in rows]}


async def _own_run(db, user, run_id: int) -> Run:
    run = await db.get(Run, run_id)
    if run is None:
        raise errors.not_found("运行", run_id)
    if run.user_id != user.id and user.role != "admin":
        raise errors.auth_forbidden("只能访问自己的运行")
    return run


@router.get("/api/evolution/{run_id}/status")
async def evolution_status(run_id: int, db: DbDep, user: UserDep):
    run = await _own_run(db, user, run_id)
    d = run_dict(run)
    d["status"] = {"provisioning": "running"}.get(run.status, run.status)
    return d


@router.get("/api/evolution/{run_id}/results")
async def evolution_results(run_id: int, db: DbDep, user: UserDep):
    run = await _own_run(db, user, run_id)
    result = run.result or {}
    return {
        "best_objective": result.get("best_objective", run.best_objective),
        "best_heuristic": result.get("best_heuristic", {}),
        "status": run.status,
    }


@router.get("/api/evolution/{run_id}/population")
async def evolution_population(run_id: int, db: DbDep, user: UserDep):
    """每代全量种群(计划痛点 #1 的正解:服务端原生落库)。"""
    run = await _own_run(db, user, run_id)
    rows = (await db.scalars(
        select(Generation).where(Generation.run_id == run.id)
        .order_by(Generation.generation))).all()
    return {
        "generations": [
            {"generation": g.generation, "best_objective": g.best_objective,
             "snapshot": g.snapshot}
            for g in rows
        ],
        # 官方形状近似:最新代个体列表平铺在 individuals
        "individuals": (rows[-1].snapshot or {}).get("individuals", [])
        if rows else [],
    }


@router.get("/api/evolution/{run_id}/prompt")
async def evolution_prompt(run_id: int, db: DbDep, user: UserDep):
    run = await _own_run(db, user, run_id)
    return {"prompt": (run.config or {}).get("llm_prompt_override", ""),
            "history": []}


@router.post("/api/evolution/{run_id}/prompt")
async def evolution_prompt_set(run_id: int, request: Request,
                               db: DbDep, user: UserDep):
    """追加自定义指令,注入引擎后续每代生成的提示词。"""
    run = await _own_run(db, user, run_id)
    body = await request.json()
    prompt = str(body.get("prompt") or "").strip()
    config = dict(run.config or {})
    config["llm_prompt_override"] = prompt
    run.config = config
    await db.commit()
    return {"ok": True, "prompt": prompt}


@router.post("/api/evolution/{run_id}/{action}")
async def evolution_action(run_id: int, action: str, request: Request,
                           db: DbDep, user: UserDep):
    """官方 action 语义:stop=停止;submit=以当前最优创建提交;其余不支持。"""
    ctx = request.app.state.ctx
    run = await _own_run(db, user, run_id)

    if action == "stop":
        final = await ctx.orchestrator.request_cancel(run.id)
        return {"ok": True, "status": final}

    if action == "submit":
        if not ctx.orchestrator.is_terminal(run.status):
            raise errors.conflict("RUN_NOT_FINISHED", "运行尚未结束,无法提交")
        # 防重复:同一 run 已有提交(手动或自动)直接返回既有记录
        existing = await db.scalar(
            select(Submission).where(Submission.run_id == run.id))
        if existing is not None:
            return {"ok": True, "submission_id": existing.id,
                    "objective": existing.objective, "duplicate": True}
        problem = await db.get(Problem, run.problem_key)
        best = run.result or {}
        obj = best.get("best_objective", run.best_objective)
        if obj is None:
            raise errors.conflict("SUBMIT_EMPTY", "运行没有可提交的最优值")
        if abs(float(obj)) >= 10 ** 9:
            # 平台语义:罚值(inf)不上榜 —— 全违规的运行没有可提交的东西
            raise errors.conflict(
                "SUBMIT_PENALTY", "运行最优值为罚值(全部候选违规),不可提交",
                detail={"objective": obj})
        sub = Submission(user_id=user.id, problem_key=run.problem_key,
                         run_id=run.id, objective=float(obj), is_official=True,
                         detail={"instance": {"config": {
                             "ascend": run.config.get("ascend",
                                                      problem.ascend if problem else True),
                             "problem_key": run.problem_key,
                         }}, "result": {"best_heuristic": best.get("best_heuristic")}},
                         created_at=now_utc())
        db.add(sub)
        await db.flush()
        await audit(db, actor=user.username, action="submission.create",
                    target=f"submission:{sub.id}")
        await db.commit()
        return {"ok": True, "submission_id": sub.id, "objective": obj}

    raise errors.invalid_input(f"不支持的操作: {action}")


# ---- 实例存档(官方形状最小实现) ----

@router.post("/api/instances", status_code=201)
async def save_instance(request: Request, db: DbDep, user: UserDep):
    body = await request.json()
    run_id = body.get("run_id")
    if run_id is None:
        raise errors.invalid_input("缺少 run_id")
    run = await db.get(Run, int(run_id))
    if run is None:
        raise errors.not_found("运行", run_id)
    if run.user_id != user.id and user.role != "admin":
        raise errors.auth_forbidden("只能保存自己的运行实例")
    detail = dict(run.config or {})
    detail.update({"instance_name": body.get("name") or "",
                   "saved_at": now_utc().isoformat()})
    run.config = detail
    await db.commit()
    return {"ok": True, "id": run.id, "name": body.get("name") or ""}


@router.get("/api/instances")
async def list_instances(db: DbDep, user: UserDep, limit: int = 50):
    rows = (await db.scalars(
        select(Run).where(Run.user_id == user.id)
        .order_by(Run.id.desc()).limit(min(limit, 200)))).all()
    return {"instances": [
        {"id": r.id, "name": (r.config or {}).get("instance_name", ""),
         "problem_key": r.problem_key, "status": r.status,
         "best_objective": r.best_objective,
         "created_at": r.created_at.isoformat() if r.created_at else None}
        for r in rows
    ]}
