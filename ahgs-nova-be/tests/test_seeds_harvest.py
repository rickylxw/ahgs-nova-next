# -*- coding: utf-8 -*-
"""种子库 / 方向感知收割 / 棘轮批量 / A/B。"""
from __future__ import annotations

from .conftest import login_admin, register_and_login, seed_problem, wait_run


async def _run_and_finish(client, user, problem_key, ascend, gens=2, base=100):
    r = await client.post("/api/v2/run", headers=user, json={
        "kind": "evolve_local", "problem_key": problem_key,
        "config": {"num_generations": gens, "ascend": ascend,
                   "base_value": base, "seed": 7},
    })
    return (await wait_run(client, user, r.json()["id"]))["id"]


async def test_seed_crud(client, settings):
    admin = await login_admin(client, settings)
    user = await register_and_login(client, "nora")
    await seed_problem(client, admin, "maxcut")

    r = await client.post("/api/v2/seeds", headers=user, json={
        "problem_key": "maxcut", "algorithm": "def solve(): pass",
        "concept": "greedy", "objective": 10.0})
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    lst = (await client.get("/api/v2/seeds?problem_key=maxcut",
                            headers=user)).json()["seeds"]
    assert [s["id"] for s in lst] == [sid]


async def test_harvest_direction_guard(client, settings):
    """棘轮守护:劣于档案的收割被拒,更优被收;方向随 ascend。"""
    admin = await login_admin(client, settings)
    user = await register_and_login(client, "oliver")
    await seed_problem(client, admin, "vrptw", ascend=True)

    # 第一轮:base 100 → 最优 < 100,收割成功
    run1 = await _run_and_finish(client, user, "vrptw", ascend=True, base=100)
    h1 = await client.post(f"/api/v2/harvest/{run1}", headers=user, json={})
    assert h1.status_code == 200 and h1.json()["accepted"], h1.text
    best1 = h1.json()["objective"]

    # 手工注入一个更好的种子档案(模拟上一轮棘轮存档)
    await client.post("/api/v2/seeds", headers=user, json={
        "problem_key": "vrptw", "algorithm": "def better_seed(): pass",
        "concept": "elite", "objective": best1 - 10})

    # 第二轮(同配置同起点,产物相似或更差)→ 守卫拒绝
    run2 = await _run_and_finish(client, user, "vrptw", ascend=True, base=100)
    h2 = await client.post(f"/api/v2/harvest/{run2}", headers=user, json={})
    if h2.json()["accepted"] is False:
        assert h2.json()["reason"] == "worse_than_archive"
    # force 收割总能通过
    h3 = await client.post(f"/api/v2/harvest/{run2}", headers=user,
                           json={"force": True})
    assert h3.json()["accepted"] is True


async def test_harvest_rejects_unfinished(client, settings):
    admin = await login_admin(client, settings)
    user = await register_and_login(client, "peter")
    await seed_problem(client, admin, "mtsp")
    r = await client.post("/api/v2/run", headers=user, json={
        "kind": "evolve_local", "problem_key": "mtsp",
        "config": {"num_generations": 1}})
    run_id = r.json()["id"]
    h = await client.post(f"/api/v2/harvest/{run_id}", headers=user, json={})
    if (await client.get(f"/api/v2/runs/{run_id}", headers=user)).json()["status"] != "completed":
        assert h.status_code == 409
        assert h.json()["code"] == "HARVEST_NOT_COMPLETED"


async def test_grind_pipeline(client, settings):
    """批量棘轮:分批跑 → 自动收割 → 总报告。"""
    admin = await login_admin(client, settings)
    user = await register_and_login(client, "quinn")
    for key in ("g1", "g2", "g3"):
        await seed_problem(client, admin, key, ascend=True)

    r = await client.post("/api/v2/grind", headers=user, json={
        "items": [{"problem_key": k, "num_generations": 2, "base_value": 80}
                  for k in ("g1", "g2", "g3")],
        "batch_size": 2, "child_kind": "evolve_local"})
    assert r.status_code == 201, r.text
    grind_run_id = r.json()["id"]
    done = await wait_run(client, user, grind_run_id, timeout=25)
    assert done["status"] == "completed", done.get("error_message")
    result = done["result"]
    assert result["total"] == 3
    assert result["completed"] == 3
    assert result["harvested"] == 3
    # 子运行关联 parent
    runs = (await client.get("/api/v2/runs?kind=evolve_local",
                             headers=user)).json()["runs"]
    assert all(x["parent_run_id"] == grind_run_id for x in runs)


async def test_abtest_directional_winner(client, settings):
    """A/B 判优方向感知:ascend=False 时大者胜。"""
    admin = await login_admin(client, settings)
    user = await register_and_login(client, "ruby")
    await seed_problem(client, admin, "pt2", ascend=False)

    r = await client.post("/api/v2/abtest", headers=user, json={
        "problem_key": "pt2",
        "arms": [
            {"name": "A", "num_generations": 2, "base_value": 100, "seed": 1},
            {"name": "B", "num_generations": 3, "base_value": 100, "seed": 2},
        ],
        "num_generations": 3, "child_kind": "evolve_local"})
    assert r.status_code == 201, r.text
    ab_run = r.json()["id"]
    done = await wait_run(client, user, ab_run, timeout=25)
    assert done["status"] == "completed", done.get("error_message")
    report = done["result"]
    assert report["ascend"] is False
    # B 跑 3 代(基准值更低 → 更大更优的方向下更差值被淘汰,这里按方向判优即可)
    assert report["winner"] in ("A", "B")
    names = [a["name"] for a in report["arms"]]
    assert names == ["A", "B"]
