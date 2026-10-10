# -*- coding: utf-8 -*-
"""standalone 兼容层:官方契约同形 + 安全修复。"""
from __future__ import annotations

from .conftest import login_admin, register_and_login, seed_problem, wait_run


async def test_compat_login_official_shape(client):
    await register_and_login(client, "cuser")
    r = await client.post("/api/auth/login",
                          json={"username": "cuser", "password": "password-123",
                                "agree_terms": True})
    assert r.status_code == 200
    d = r.json()
    assert "access_token" in d and d["user"]["username"] == "cuser"


async def test_compat_problems_and_ranking_ascend(client, settings):
    """ascend=False:分高者排前;同分先到先得。"""
    admin = await login_admin(client, settings)
    await seed_problem(client, admin, "pt3", ascend=False)
    alice = await register_and_login(client, "ranker_a")
    bob = await register_and_login(client, "ranker_b")

    token_alice = (await client.post("/api/auth/login", json={
        "username": "ranker_a", "password": "password-123"})).json()["access_token"]
    token_bob = (await client.post("/api/auth/login", json={
        "username": "ranker_b", "password": "password-123"})).json()["access_token"]

    # 直接以 compat evolution start → 完成 → submit 产生提交
    for token, base, gens in ((token_alice, 100, 2), (token_bob, 100, 3)):
        r = await client.post("/api/evolution/start",
                              headers={"Authorization": f"Bearer {token}"},
                              json={"problem_key": "pt3",
                                    "num_generations": gens,
                                    "ascend": False,
                                    "base_value": base})
        assert r.status_code == 200, r.text
        run_id = r.json()["run_id"]
        await wait_run(client, {"Authorization": f"Bearer {token}"}, run_id)
        s = await client.post(f"/api/evolution/{run_id}/submit",
                              headers={"Authorization": f"Bearer {token}"})
        assert s.status_code == 200, s.text

    rank = (await client.get("/api/ranking/pt3")).json()
    assert rank["ascend"] is False
    entries = rank["entries"]
    assert len(entries) == 2
    assert entries[0]["rank"] == 1
    # 跑 3 代的 bob 最优应 ≥ 跑 2 代的 alice(越大越好方向)
    assert entries[0]["best_objective"] >= entries[1]["best_objective"]


async def test_compat_problems_shape(client, settings):
    admin = await login_admin(client, settings)
    await seed_problem(client, admin, "tsp9", ascend=True,
                       contract={"fun_name": "select_next_node",
                                 "fun_args": ["instance", "current_node"]})
    lst = (await client.get("/api/problems")).json()["problems"]
    assert any(p["key"] == "tsp9" for p in lst)
    d = (await client.get("/api/problems/tsp9")).json()
    assert d["fun_name"] == "select_next_node"
    assert d["ascend"] is True


async def test_user_detail_requires_auth(client, settings):
    """安全报告 §5 修复:用户详情/轨迹强制登录。"""
    user = await register_and_login(client, "secuser")
    uid = (await client.get("/api/v2/auth/me", headers=user)).json()["id"]
    r1 = await client.get(f"/api/users/{uid}")
    assert r1.status_code == 401
    r2 = await client.get(f"/api/users/{uid}/submissions")
    assert r2.status_code == 401
    r3 = await client.get(f"/api/users/{uid}", headers=user)
    assert r3.status_code == 200


async def test_compat_recent_and_record(client, settings):
    admin = await login_admin(client, settings)
    user = await register_and_login(client, "rec")
    await seed_problem(client, admin, "tsp10")
    r = await client.post("/api/evolution/start", headers=user, json={
        "problem_key": "tsp10", "num_generations": 2, "ascend": True})
    run_id = r.json()["run_id"]
    await wait_run(client, user, run_id)
    await client.post(f"/api/evolution/{run_id}/submit", headers=user)

    recent = (await client.get("/api/submissions/recent?limit=10")).json()
    assert len(recent["submissions"]) == 1
    sid = recent["submissions"][0]["id"]
    rec = (await client.get(f"/api/submissions/{sid}/record",
                            headers=user)).json()
    assert rec["instance"]["config"]["ascend"] is True


async def test_compat_population_endpoint(client, settings):
    admin = await login_admin(client, settings)
    user = await register_and_login(client, "pop")
    await seed_problem(client, admin, "tsp11")
    r = await client.post("/api/evolution/start", headers=user, json={
        "problem_key": "tsp11", "num_generations": 3})
    run_id = r.json()["run_id"]
    await wait_run(client, user, run_id)
    pop = (await client.get(f"/api/evolution/{run_id}/population",
                            headers=user)).json()
    assert len(pop["generations"]) == 3
    assert pop["individuals"]  # 最新代个体平铺


async def test_compat_llm_presets_from_chain(client):
    """llm-presets 由网关降级链生成真实预设(id=模型名)。"""
    r = await client.get("/api/llm-presets")
    assert r.status_code == 200
    presets = r.json()["presets"]
    assert isinstance(presets, list) and presets
    p0 = presets[0]
    assert {"id", "name", "provider", "base_url"} <= set(p0)


async def test_compat_start_with_nova_payload(client, settings):
    """回归:NOVA EvoView 载荷(fun_args/fun_return 为 JSON 数组)曾因 schema
    声明为 str 而 422「请求参数校验失败」。"""
    admin = await login_admin(client, settings)
    user = await register_and_login(client, "nova_evo")
    await client.put("/api/v2/admin/problems/nova-p", headers=admin,
                     json={"name": "nova-p", "kind": "optimization"})

    body = {
        "problem_key": "nova-p",
        "framework_type": "eoh_nseh",
        "population_size": 8,
        "num_generations": 1,
        "num_mutation": 3,
        "num_hybridization": 3,
        "num_reflection": 3,
        "num_policy_updates": 1,
        "preset_id": "local",
        "llm_model": None,
        "llm_base_url": None,
        "use_local_llm": True,
        "problem_override": "",
        "fun_name": "select_item",
        "fun_args": ["current_index", "remaining_capacity", "weights", "values", "num_items"],
        "fun_return": ["take_item"],
        "fun_notes": "notes",
        "ascend": True,
        "problem_path": "problems/x",
        "train_data": "train.pkl",
        "train_solution": "sol.pkl",
    }
    r = await client.post("/api/evolution/start", headers=user, json=body)
    assert r.status_code == 200, r.text
    run_id = r.json()["run_id"]
    run = (await client.get(f"/api/v2/runs/{run_id}", headers=user)).json()
    assert run["config"]["fun_return"] == ["take_item"]
    assert run["config"]["fun_args"][0] == "current_index"
