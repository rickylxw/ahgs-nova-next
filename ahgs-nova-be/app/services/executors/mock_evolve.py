# -*- coding: utf-8 -*-
"""本地模拟执行器:无需官方平台即可演示/测试完整运行生命周期。

模拟一次进化:每代产出种群快照、best 逐代改善(方向感知),结束时产出与官方
同构的 results(best_heuristic),使 CurveView/收割/棘轮全链路可独立联调。
"""
from __future__ import annotations

import asyncio
import random

from .base import RunContext, RunExecutor


class MockEvolveExecutor(RunExecutor):
    kind = "evolve_local"

    def __init__(self, step_delay: float = 0.05):
        self.step_delay = step_delay

    async def execute(self, ctx: RunContext) -> dict:
        cfg = ctx.run.config
        gens = int(cfg.get("num_generations") or 5)
        pop_size = int(cfg.get("population_size") or 8)
        ascend = bool(cfg.get("ascend", True))
        base = float(cfg.get("base_value") or 100.0)
        noise = random.Random(cfg.get("seed") or ctx.run.id)

        best = None
        for g in range(1, gens + 1):
            await asyncio.sleep(self.step_delay)
            individuals = []
            for i in range(pop_size):
                obj = base / g + noise.uniform(-1, 1)
                individuals.append({
                    "id": f"g{g}-{i}", "objective": round(obj, 4),
                    "concept": f"gen{g} individual {i}",
                })
            if ascend:
                gen_best = min(i["objective"] for i in individuals)
            else:
                gen_best = max(i["objective"] for i in individuals)
            if best is None or (gen_best < best if ascend else gen_best > best):
                best = gen_best
            await ctx.set_generation(g, best, {"individuals": individuals})

        return {
            "best_objective": best,
            "best_heuristic": {
                "algorithm": "def solve(instance):\n    # mock heuristic\n    return None\n",
                "concept": f"mock evolution ({gens} gens)",
                "feature": ["mock"],
                "generation": gens,
            },
            "generations": gens,
        }
