# -*- coding: utf-8 -*-
"""A/B 对照执行器(计划 §4.5:复刻 wave-13 A/B 实验)。

config 形如:
{
  "problem_key": "...",
  "arms": [ {name, template|framework_code, seed_id?}, ... ],
  "num_generations": 5, "llm_model": "...",
  "child_kind": "evolve_official" | "evolve_local"
}
并行启动各臂子运行,全部结束后按题目 ascend 方向判优出报告,写入 abtests.result。
"""
from __future__ import annotations

import asyncio

from ...core import errors
from .base import RunContext, RunExecutor


class AbTestExecutor(RunExecutor):
    kind = "abtest"

    async def execute(self, ctx: RunContext) -> dict:
        from ...db.models import AbTest

        cfg = ctx.run.config
        problem_key = cfg.get("problem_key") or ctx.run.problem_key
        arms: list[dict] = list(cfg.get("arms") or [])
        if len(arms) < 2:
            raise errors.invalid_input("A/B 实验至少需要两个臂")
        child_kind = cfg.get("child_kind") or "evolve_official"

        abtest = AbTest(
            user_id=ctx.run.user_id, problem_key=problem_key,
            arms=[], status="running", created_at=ctx.run.created_at,
        )
        ctx.db.add(abtest)
        await ctx.db.flush()

        child_ids = []
        for arm in arms:
            config = {k: v for k, v in arm.items() if k != "name"}
            config.setdefault("problem_key", problem_key)
            config.setdefault("num_generations", cfg.get("num_generations"))
            if cfg.get("llm_model"):
                config.setdefault("llm_model", cfg["llm_model"])
            child = await ctx.orchestrator.enqueue_run(
                ctx.db, user_id=ctx.run.user_id, kind=child_kind,
                problem_key=problem_key, config=config,
                total_generations=int(cfg.get("num_generations") or 0),
                seed_id=arm.get("seed_id"), parent_run_id=ctx.run.id,
                secrets=ctx.secrets,
            )
            child_ids.append(child.id)
            abtest.arms = list(abtest.arms or []) + [
                {"name": arm.get("name") or f"arm_{len(child_ids)}", "run_id": child.id}
            ]
            await ctx.db.commit()
            await ctx.emit("abtest_arm_started",
                           {"abtest_id": abtest.id, "arm": arm.get("name"),
                            "run_id": child.id})

        await asyncio.gather(*(ctx.orchestrator.wait_for_run(cid) for cid in child_ids))

        report = await self._build_report(ctx, abtest, arms, child_ids)
        abtest.result = report
        abtest.status = "completed"
        await ctx.db.commit()
        return {"abtest_id": abtest.id, **report}

    @staticmethod
    async def _build_report(ctx: RunContext, abtest, arms: list[dict],
                            child_ids: list[int]) -> dict:
        from ...db.models import Problem, Run
        from ..orchestrator import Orchestrator

        problem = await ctx.db.get(Problem, abtest.problem_key)
        ascend = problem.ascend if problem else True

        rows = []
        winner_idx = None
        for arm, cid in zip(arms, child_ids):
            run = await ctx.db.get(Run, cid)
            best = run.best_objective
            improved = best is not None and (
                winner_idx is None
                or Orchestrator._better(best, rows[winner_idx]["best_objective"], ascend)
            )
            if improved:
                winner_idx = len(rows)
            rows.append({
                "name": arm.get("name") or f"arm_{cid}", "run_id": cid,
                "status": run.status, "best_objective": best,
                "error_code": run.error_code,
            })
        return {
            "ascend": ascend,
            "arms": rows,
            "winner": rows[winner_idx]["name"] if winner_idx is not None else None,
        }
