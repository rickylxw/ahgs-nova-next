# -*- coding: utf-8 -*-
"""ELO 积分(标准 K=32;逐局更新)。

apply_pair:双人局(legacy 路径)。apply_ranking:多人同局(名次组制)——
线性名次分(第 1 名 1 分、末名 0 分、并列均分)对战场期望分,n=2 时与
apply_pair 完全一致,且严格零和(Σ名次分 = Σ期望分 = n/2)。
"""
from __future__ import annotations

K = 32.0


def expected(rating_a: float, rating_b: float) -> float:
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400.0))


def apply_pair(rating_a: float, rating_b: float, score_a: float,
               k: float = K) -> tuple[float, float]:
    """score_a ∈ {1, 0.5, 0}。返回 (新 a, 新 b)。"""
    ea = expected(rating_a, rating_b)
    da = k * (score_a - ea)
    return rating_a + da, rating_b - da


def apply_ranking(ratings: dict[int, float], ranking: list[list[int]],
                  k: float = K) -> None:
    """多人同局 ELO 更新(原地修改 ratings)。

    ranking 为名次组、最佳在前,组内并列(如 [[2],[1,4],[3]] = 2 冠军,
    1/4 并列次名,3 末位)。每名玩家每局只更新一次,幅度与双人局同量级。
    """
    flat = [pid for group in ranking for pid in group]
    n = len(flat)
    if n < 2 or set(flat) != set(ratings) or len(flat) != n:
        return
    exp = {pid: sum(expected(ratings[pid], ratings[q]) for q in flat if q != pid)
           / (n - 1) for pid in flat}
    slot = 1
    for group in ranking:
        m = len(group)
        score = sum((n - (slot + j)) / (n - 1) for j in range(m)) / m
        for pid in group:
            ratings[pid] += k * (score - exp[pid])
        slot += m
