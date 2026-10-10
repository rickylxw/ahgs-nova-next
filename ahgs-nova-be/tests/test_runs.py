# -*- coding: utf-8 -*-
"""运行编排:生命周期 / 每代快照 / 取消 / 题目类型白名单。"""
from __future__ import annotations

import asyncio

from .conftest import login_admin, register_and_login, seed_problem, wait_run


async def test_mock_run_lifecycle_and_generations(client, settings):
    admin = await login_admin(client, settings)
    user = await register_and_login(client, "gina")
    await seed_problem(client, admin, "knapsack", ascend=True)

    r = await client.post("/api/v2/run", headers=user, json={
        "kind": "evolve_local", "problem_key": "knapsack",
        "total_generations": 3,
        "config": {"num_generations": 3, "ascend": True, "base_value": 90,
                   "population_size": 4},
    })
    assert r.status_code == 201, r.text
    run_id = r.json()["id"]

    done = await wait_run(client, user, run_id)
    assert done["status"] == "completed"
    assert done["best_objective"] is not None

    gens = (await client.get(f"/api/v2/runs/{run_id}/generations",
                             headers=user)).json()["generations"]
    assert [g["generation"] for g in gens] == [1, 2, 3]
    # best 单调不回退(ascend=小更优)
    bests = [g["best_objective"] for g in gens]
    assert all(b1 >= b2 for b1, b2 in zip(bests, bests[1:]))  # 小更优 → 非增
    # 种群全量落库
    assert len(gens[0]["snapshot"]["individuals"]) == 4


async def test_run_descend_direction(client, settings):
    """ascend=False:越大越好(power_trading 类)。"""
    admin = await login_admin(client, settings)
    user = await register_and_login(client, "henry")
    await seed_problem(client, admin, "power_trading", ascend=False)

    r = await client.post("/api/v2/run", headers=user, json={
        "kind": "evolve_local", "problem_key": "power_trading",
        "config": {"num_generations": 3, "ascend": False, "base_value": 50},
    })
    run_id = r.json()["id"]
    done = await wait_run(client, user, run_id)
    gens = (await client.get(f"/api/v2/runs/{run_id}/generations",
                             headers=user)).json()["generations"]
    bests = [g["best_objective"] for g in gens]
    assert all(b1 <= b2 for b1, b2 in zip(bests, bests[1:]))  # 大更优 → 非减


async def test_run_kind_whitelist_for_game_problems(client, settings):
    """game 类题目只允许对战负载 —— 编排器入队校验。"""
    admin = await login_admin(client, settings)
    user = await register_and_login(client, "iris")
    await seed_problem(client, admin, "chessgame", kind="game")

    r = await client.post("/api/v2/run", headers=user, json={
        "kind": "evolve_local", "problem_key": "chessgame",
        "config": {"num_generations": 2},
    })
    assert r.status_code == 422
    assert r.json()["code"] == "INVALID_INPUT"


async def test_cancel_queued_run(client, settings):
    admin = await login_admin(client, settings)
    user = await register_and_login(client, "jack")
    await seed_problem(client, admin, "tsp")
    await client.post("/api/v2/admin/queue/pause", headers=admin,
                      json={"paused": True, "reason": "测试暂停",
                            "resume_at": "2026-10-01T00:00:00"})
    r = await client.post("/api/v2/run", headers=user, json={
        "kind": "evolve_local", "problem_key": "tsp",
        "config": {"num_generations": 1},
    })
    assert r.status_code == 503
    assert r.json()["code"] == "QUEUE_PAUSED"  # 显式"数据保护中"语义

    await client.post("/api/v2/admin/queue/pause", headers=admin,
                      json={"paused": False})
    r = await client.post("/api/v2/run", headers=user, json={
        "kind": "evolve_local", "problem_key": "tsp",
        "config": {"num_generations": 1},
    })
    run_id = r.json()["id"]
    c = await client.post(f"/api/v2/runs/{run_id}/cancel", headers=user,
                          json={"reason": "不想跑了"})
    assert c.status_code == 200
    await asyncio.sleep(0.3)
    d = (await client.get(f"/api/v2/runs/{run_id}", headers=user)).json()
    assert d["status"] in ("canceled", "completed")


async def test_run_isolation_between_users(client, settings):
    admin = await login_admin(client, settings)
    alice = await register_and_login(client, "kate")
    await register_and_login(client, "liam")
    await seed_problem(client, admin, "tsp2")

    r = await client.post("/api/v2/run", headers=alice, json={
        "kind": "evolve_local", "problem_key": "tsp2",
        "config": {"num_generations": 2}})
    run_id = r.json()["id"]
    other = await register_and_login(client, "mike")
    r2 = await client.get(f"/api/v2/runs/{run_id}", headers=other)
    assert r2.status_code == 403
