# -*- coding: utf-8 -*-
"""批量棘轮执行器(计划 §4.5:替代 _grind.py 的分批/重试/收割循环)。

config 形如:
{
  "items": [ {problem_key, template|framework_code, seed_id?, num_generations,
              llm_model?, auto_harvest?}, ... ],
  "batch_size": 3,        # 每批并发数(冲榜记录 §6:≤3 并发评估最稳)
  "child_kind": "evolve_official" | "evolve_local",
}
子运行以 parent_run_id 关联;每批完成后收割(方向守卫内置),全部结束出报告。
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from ...core import errors
from .base import RunContext, RunExecutor, RunSecrets

log = logging.getLogger("nova.exec.grind")


class GrindExecutor(RunExecutor):
    kind = "grind"

    def __init__(self, batch_size: int = 3):
        self.batch_size = batch_size

    async def execute(self, ctx: RunContext) -> dict:
        cfg = ctx.run.config
        items: list[dict] = list(cfg.get("items") or [])
        if not items:
            raise errors.invalid_input("grind.items 为空")
        batch_size = max(1, int(cfg.get("batch_size") or self.batch_size))
        child_kind = cfg.get("child_kind") or "evolve_official"

        report: list[dict] = []
        for start in range(0, len(items), batch_size):
            batch = items[start:start + batch_size]
            child_ids = await self._launch_batch(ctx, batch, child_kind)
            batch_report = await self._await_batch(ctx, batch, child_ids)
            report.extend(batch_report)
            await ctx.emit("grind_batch_done", {
                "batch_index": start // batch_size + 1,
                "problems": [b["problem_key"] for b in batch],
                "results": batch_report,
            })

        harvested = [r for r in report if (r.get("harvest") or {}).get("accepted")]
        return {
            "items": report,
            "total": len(report),
            "completed": sum(1 for r in report if r["status"] == "completed"),
            "failed": sum(1 for r in report if r["status"] == "failed"),
            "harvested": len(harvested),
        }

    async def _launch_batch(self, ctx: RunContext, batch: list[dict],
                            child_kind: str) -> list[int]:
        ids = []
        for item in batch:
            config = {k: v for k, v in item.items() if k != "problem_key"}
            child = await ctx.orchestrator.enqueue_run(
                ctx.db, user_id=ctx.run.user_id, kind=child_kind,
                problem_key=item.get("problem_key"),
                problem_kind=self._problem_kind_of(ctx, item.get("problem_key")),
                config=config,
                total_generations=int(item.get("num_generations") or 0),
                seed_id=item.get("seed_id"),
                parent_run_id=ctx.run.id,
                secrets=ctx.secrets,
            )
            ids.append(child.id)
        await ctx.db.commit()
        return ids

    @staticmethod
    def _problem_kind_of(ctx: RunContext, problem_key: str | None) -> str | None:
        # 子运行题目类型由 API 层入队 grind 时校验过,这里不再回查
        return None

    async def _await_batch(self, ctx: RunContext, batch: list[dict],
                           child_ids: list[int]) -> list[dict]:
        orch = ctx.orchestrator
        rows = []
        for item, child_id in zip(batch, child_ids):
            await orch.wait_for_run(child_id)
            rows.append(await self._child_summary(ctx.db, item, child_id))
        return rows

    @staticmethod
    async def _child_summary(db: AsyncSession, item: dict, child_id: int) -> dict:
        from ...db.models import Run

        run = await db.get(Run, child_id)
        if run.status not in ("completed", "failed", "canceled"):
            # 身份映射可能仍是创建时的旧状态,终态判定前强制回读
            await db.refresh(run)
        summary = {
            "problem_key": run.problem_key,
            "child_run_id": run.id,
            "status": run.status,
            "best_objective": run.best_objective,
            "error_code": run.error_code,
        }
        # 棘轮语义:grind 的子运行默认收割(方向守卫内置),item.auto_harvest=False 显式关闭
        if run.status == "completed" and item.get("auto_harvest", True):
            try:
                summary["harvest"] = await _do_harvest(db, run.id)
                # 立即提交:保证种子落库,并马上释放写锁 —— 否则跨 await 的未提交
                # 写事务会阻塞其他会话的每代快照(SQLite BUSY),最后一批还会被回滚
                await db.commit()
            except errors.NovaError as e:
                await db.rollback()
                summary["harvest"] = {"accepted": False, "reason": e.code}
        return summary


async def _do_harvest(db: AsyncSession, run_id: int) -> dict:
    from ..harvest import harvest_run

    return (await harvest_run(db, run_id)).as_dict()
