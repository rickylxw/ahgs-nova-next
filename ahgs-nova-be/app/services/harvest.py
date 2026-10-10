# -*- coding: utf-8 -*-
"""收割服务(计划 §4.5):方向感知地把运行产物写入种子库。

守护逻辑内置棘轮语义(冲榜记录 §4 机制 #8):
- 目标方向由 problems.ascend 决定(True=越小越好);
- 新 objective 不优于当前档案最优 → 拒绝(绝不回退);
- 更优 → 新增一条种子(档案只追加,保留历史轨迹)。
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core import errors
from ..core.security import now_utc
from ..db.models import Problem, Run, Seed


@dataclass
class HarvestVerdict:
    accepted: bool
    reason: str
    seed_id: int | None = None
    objective: float | None = None
    incumbent: float | None = None

    def as_dict(self) -> dict:
        return {
            "accepted": self.accepted, "reason": self.reason,
            "seed_id": self.seed_id, "objective": self.objective,
            "incumbent": self.incumbent,
        }


def better(candidate: float, incumbent: float | None, ascend: bool) -> bool:
    if incumbent is None:
        return True
    return candidate < incumbent if ascend else candidate > incumbent


async def best_seed(db: AsyncSession, problem_key: str) -> Seed | None:
    """当前档案最优种子(按题目方向判优)。"""
    problem = await db.get(Problem, problem_key)
    ascend = problem.ascend if problem else True
    rows = (await db.scalars(
        select(Seed).where(Seed.problem_key == problem_key)
    )).all()
    best: Seed | None = None
    for s in rows:
        if s.objective is None:
            continue
        if best is None or better(s.objective, best.objective, ascend):
            best = s
    return best


async def harvest_run(db: AsyncSession, run_id: int, *,
                      force: bool = False) -> HarvestVerdict:
    run = await db.get(Run, run_id)
    if run is None:
        raise errors.not_found("运行", run_id)
    if run.status != "completed":
        raise errors.conflict("HARVEST_NOT_COMPLETED",
                              f"运行尚未完成(status={run.status})",
                              detail={"status": run.status})
    result = run.result or {}
    bh = result.get("best_heuristic") or {}
    code = bh.get("algorithm", "")
    if not code:
        raise errors.conflict("HARVEST_EMPTY", "运行结果中没有可收割的启发式代码")

    problem = await db.get(Problem, run.problem_key)
    if problem is None:
        raise errors.not_found("题目", run.problem_key)
    ascend = problem.ascend

    objective = result.get("best_objective")
    if objective is None:
        objective = run.best_objective

    incumbent = await best_seed(db, run.problem_key)
    inc_obj = incumbent.objective if incumbent else None
    if not force and incumbent is not None and objective is not None \
            and not better(objective, inc_obj, ascend):
        return HarvestVerdict(False, "worse_than_archive",
                              incumbent.id, objective, inc_obj)

    seed = Seed(
        problem_key=run.problem_key, algorithm=code,
        concept=bh.get("concept", ""), feature=bh.get("feature", []) or [],
        objective=objective, source="harvest", source_run_id=run.id,
        generation=bh.get("generation"), created_at=now_utc(), updated_at=now_utc(),
    )
    db.add(seed)
    await db.flush()
    return HarvestVerdict(True, "harvested", seed.id, objective, inc_obj)
