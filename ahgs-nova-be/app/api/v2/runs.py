# -*- coding: utf-8 -*-
"""v2 运行与冲榜原语:统一运行入口、查询、取消、每代快照、收割、棘轮批量、A/B。"""
from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import select

from ...core import errors
from ...core.audit import audit
from ...core.security import now_utc
from ...db.models import Generation, Problem, Run
from ...schemas import AbTestIn, CancelIn, GrindIn, HarvestIn, RunIn
from ...services.executors.base import RunSecrets
from ...services.harvest import harvest_run
from ..deps import DbDep, UserDep

router = APIRouter(tags=["v2-runs"])

# 契约无 evaluate 规格时的兜底执行器(演示/联调用);有规格自动选本地进化引擎
DEFAULT_KIND = "evolve_local"


def resolve_default_kind(problem: "Problem | None") -> str:
    """契约带 evaluate 规格的题目默认走本地进化引擎,否则用演示执行器。"""
    if problem is not None and bool((problem.contract or {}).get("evaluate") or {}):
        return "evolve_llm"
    return DEFAULT_KIND


def run_dict(run: Run, include_config: bool = False) -> dict:
    d = {
        "id": run.id, "kind": run.kind, "status": run.status,
        "user_id": run.user_id, "problem_key": run.problem_key,
        "priority": run.priority,
        "current_generation": run.current_generation,
        "total_generations": run.total_generations,
        "best_objective": run.best_objective,
        "seed_id": run.seed_id, "parent_run_id": run.parent_run_id,
        "official_run_id": run.official_run_id,
        "error_code": run.error_code, "error_message": run.error_message,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }
    if include_config:
        d["config"] = run.config
    if run.result is not None:
        d["result"] = run.result
    return d


async def _own_run(db: DbDep, user, run_id: int) -> Run:
    run = await db.get(Run, run_id)
    if run is None:
        raise errors.not_found("运行", run_id)
    if run.user_id != user.id and user.role != "admin":
        raise errors.auth_forbidden("只能访问自己的运行")
    return run


def _extract_secrets(secrets: dict) -> RunSecrets:
    return RunSecrets(
        llm_api_key=str(secrets.get("llm_api_key") or ""),
        extra={k: str(v) for k, v in secrets.items() if k != "llm_api_key"},
    )


def _sanitize_config(config: dict) -> dict:
    """落库前剥掉敏感字段(secrets 走独立通道,不进 JSONB)。"""
    return {k: v for k, v in (config or {}).items()
            if k not in ("api_key", "llm_api_key")}


@router.post("/api/v2/run", status_code=201)
async def create_run(body: RunIn, request: Request, db: DbDep, user: UserDep):
    """统一运行入口。

    - kind 留空自动选择:契约带 evaluate 规格走本地进化引擎,否则演示执行器;
    - evolve 类运行需要 config.framework_code 或 config.template(+seed_id);
    - 批量棘轮与 A/B 走专用端点(/api/v2/grind、/api/v2/abtest);
    - 对战走 /api/v2/arena/matches。
    """
    ctx = request.app.state.ctx
    problem = None
    if body.problem_key is not None:
        problem = await db.get(Problem, body.problem_key)
        if problem is None:
            raise errors.not_found("题目", body.problem_key)
    kind = body.kind or resolve_default_kind(problem)
    if kind in ("grind", "abtest"):
        raise errors.invalid_input(
            f"kind={kind} 请使用专用端点 /api/v2/{kind}")
    problem_kind = body.problem_kind or (problem.kind if problem else None)

    run = await ctx.orchestrator.enqueue_run(
        db, user_id=user.id, kind=kind,
        problem_key=body.problem_key, problem_kind=problem_kind,
        config=_sanitize_config(body.config), priority=body.priority,
        total_generations=body.total_generations, seed_id=body.seed_id,
        secrets=_extract_secrets(body.secrets),
    )
    await audit(db, actor=user.username, action="run.enqueue",
                target=f"run:{run.id}", detail={"kind": kind,
                                                "problem_key": body.problem_key})
    await db.commit()
    return run_dict(run)


@router.get("/api/v2/runs")
async def list_runs(request: Request, db: DbDep, user: UserDep,
                    status: str | None = None, kind: str | None = None,
                    problem_key: str | None = None, all_users: bool = False,
                    limit: int = 50, offset: int = 0):
    ctx = request.app.state.ctx
    q = select(Run).order_by(Run.id.desc()).limit(min(limit, 200)).offset(offset)
    if not (all_users and user.role == "admin"):
        q = q.where(Run.user_id == user.id)
    if status:
        q = q.where(Run.status == status)
    if kind:
        q = q.where(Run.kind == kind)
    if problem_key:
        q = q.where(Run.problem_key == problem_key)
    rows = (await db.scalars(q)).all()
    return {"runs": [run_dict(r) for r in rows],
            "queue_depth": ctx.queue.depth}


@router.get("/api/v2/runs/{run_id}")
async def get_run(run_id: int, db: DbDep, user: UserDep):
    run = await _own_run(db, user, run_id)
    return run_dict(run, include_config=True)


@router.post("/api/v2/runs/{run_id}/cancel")
async def cancel_run(run_id: int, body: CancelIn, request: Request,
                     db: DbDep, user: UserDep):
    ctx = request.app.state.ctx
    run = await _own_run(db, user, run_id)
    final = await ctx.orchestrator.request_cancel(run.id)
    await audit(db, actor=user.username, action="run.cancel",
                target=f"run:{run.id}", detail={"reason": body.reason,
                                                "final": final})
    await db.commit()
    return {"run_id": run.id, "status": final}


@router.get("/api/v2/runs/{run_id}/generations")
async def list_generations(run_id: int, db: DbDep, user: UserDep):
    await _own_run(db, user, run_id)
    rows = (await db.scalars(
        select(Generation).where(Generation.run_id == run_id)
        .order_by(Generation.generation)
    )).all()
    return {"generations": [
        {"generation": g.generation, "best_objective": g.best_objective,
         "snapshot": g.snapshot,
         "created_at": g.created_at.isoformat() if g.created_at else None}
        for g in rows
    ]}


@router.get("/api/v2/runs/{run_id}/generations/{generation}")
async def get_generation(run_id: int, generation: int, db: DbDep, user: UserDep):
    await _own_run(db, user, run_id)
    row = await db.scalar(
        select(Generation).where(Generation.run_id == run_id,
                                 Generation.generation == generation))
    if row is None:
        raise errors.not_found("代快照", f"{run_id}/{generation}")
    return {"generation": row.generation, "best_objective": row.best_objective,
            "snapshot": row.snapshot}


# ============ 收割 / 棘轮批量 / A/B ============

@router.post("/api/v2/harvest/{run_id}")
async def harvest(run_id: int, body: HarvestIn, request: Request,
                  db: DbDep, user: UserDep):
    """方向感知收割(棘轮守护内置:劣于档案即拒绝)。"""
    ctx = request.app.state.ctx
    await _own_run(db, user, run_id)
    verdict = await harvest_run(db, run_id, force=body.force)
    await db.commit()
    await audit(db, actor=user.username, action="harvest",
                target=f"run:{run_id}", detail=verdict.as_dict())
    await db.commit()
    return verdict.as_dict()


@router.post("/api/v2/grind", status_code=201)
async def grind(body: GrindIn, request: Request, db: DbDep, user: UserDep):
    """批量棘轮:分批启动子运行,每批收割(方向守卫内置),产出总报告。"""
    ctx = request.app.state.ctx
    for item in body.items:
        if not item.get("problem_key"):
            raise errors.invalid_input("grind.items 每项都需要 problem_key")
        if await db.get(Problem, item["problem_key"]) is None:
            raise errors.not_found("题目", item["problem_key"])
    child_kind = body.child_kind or resolve_default_kind(
        await db.get(Problem, body.items[0]["problem_key"]))
    run = await ctx.orchestrator.enqueue_run(
        db, user_id=user.id, kind="grind",
        config={"items": body.items, "batch_size": body.batch_size,
                "child_kind": child_kind},
        secrets=_extract_secrets(body.secrets),
    )
    await audit(db, actor=user.username, action="grind.enqueue",
                target=f"run:{run.id}", detail={"items": len(body.items)})
    await db.commit()
    return run_dict(run)


@router.post("/api/v2/abtest", status_code=201)
async def abtest(body: AbTestIn, request: Request, db: DbDep, user: UserDep):
    """A/B 对照:并行两组子运行,完成后按 ascend 方向自动判优。"""
    ctx = request.app.state.ctx
    if await db.get(Problem, body.problem_key) is None:
        raise errors.not_found("题目", body.problem_key)
    child_kind = body.child_kind or resolve_default_kind(
        await db.get(Problem, body.items[0]["problem_key"]))
    run = await ctx.orchestrator.enqueue_run(
        db, user_id=user.id, kind="abtest", problem_key=body.problem_key,
        config={"problem_key": body.problem_key, "arms": body.arms,
                "num_generations": body.num_generations,
                "llm_model": body.llm_model, "child_kind": child_kind},
        total_generations=body.num_generations,
        secrets=_extract_secrets(body.secrets),
    )
    await audit(db, actor=user.username, action="abtest.enqueue",
                target=f"run:{run.id}", detail={"arms": len(body.arms)})
    await db.commit()
    return run_dict(run)
