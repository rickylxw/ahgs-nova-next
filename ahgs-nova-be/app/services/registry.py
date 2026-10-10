# -*- coding: utf-8 -*-
"""题目类型注册表(为对战小游戏等新玩法预留的核心扩展点)。

题目不再隐含"进化优化"一种语义。每个 kind 声明:
- 允许的运行负载 kind(evolve/arena_match/…),入队时据此校验;
- 结果如何参与榜单(best 提取规则)或是否参与榜单。

新增一种玩法 = 注册一个 ProblemKindSpec + 实现对应 RunExecutor + (可选)Arena,
编排器与 API 层零改动。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ProblemKindSpec:
    key: str                                   # "optimization" / "game" / …
    display_name: str
    allowed_run_kinds: tuple[str, ...]         # 该类题目允许的 runs.kind
    ranked: bool = True                        # 是否参与 objective 榜单
    description: str = ""


_REGISTRY: dict[str, ProblemKindSpec] = {}


def register_problem_kind(spec: ProblemKindSpec) -> None:
    _REGISTRY[spec.key] = spec


def get_problem_kind(key: str) -> ProblemKindSpec | None:
    return _REGISTRY.get(key)


def list_problem_kinds() -> list[dict]:
    return [
        {
            "key": s.key, "display_name": s.display_name,
            "allowed_run_kinds": list(s.allowed_run_kinds),
            "ranked": s.ranked, "description": s.description,
        }
        for s in _REGISTRY.values()
    ]


# ---- 内置类型 ----
register_problem_kind(ProblemKindSpec(
    key="optimization", display_name="进化优化",
    allowed_run_kinds=("evolve_official", "evolve_local", "evolve_llm", "grind", "abtest"),
    ranked=True,
    description="经典单目标进化优化:种群逐代进化,objective 参与榜单(ascend 语义)。",
))
register_problem_kind(ProblemKindSpec(
    key="game", display_name="对战竞技",
    allowed_run_kinds=("arena_match",),
    ranked=False,  # 对战类不走 objective 榜单,走 Arena ELO 榜(/api/v2/arena/leaderboard)
    description="上传对战程序互打:匹配/循环赛产生胜负,ELO 积分榜。",
))
