# -*- coding: utf-8 -*-
"""本地进化引擎:脚本化 LLM 驱动的真实进化循环 + 收割棘轮闭环。"""
from __future__ import annotations

from app.services.llm import LLMAdapter, LLMResponse  # noqa: F401

from .conftest import login_admin, register_and_login, wait_run

# 迷你背包:items=[重量,价值], 容量 10;ascend=True → objective = -价值(越小越好)
INSTANCE = {"items": [[5, 10], [4, 40], [6, 30], [3, 50]], "capacity": 10}

JUDGE = '''
def judge(instance, config, ns):
    items = instance["items"]; cap = instance["capacity"]
    try:
        chosen = list(ns["solve"](instance, config))
    except Exception:
        return 10**9
    if len(set(chosen)) != len(chosen):
        return 10**9
    w = sum(items[i][0] for i in chosen if isinstance(i, int) and 0 <= i < len(items))
    v = sum(items[i][1] for i in chosen if isinstance(i, int) and 0 <= i < len(items))
    return 10**9 if w > cap else -v
'''

WEAK_SEED = '''
def solve(instance, config):
    return [0, 1]          # 只拿前两件:w=9 v=50 → -50(弱种子)
'''

GREEDY = '''
def solve(instance, config):
    items = instance["items"]; cap = instance["capacity"]
    order = sorted(range(len(items)), key=lambda i: -items[i][1] / items[i][0])
    pick, w = [], 0
    for i in order:
        if w + items[i][0] <= cap:
            pick.append(i); w += items[i][0]
    return pick             # 性价比贪心 → -90(最优)
'''

BROKEN = '''
def solve(instance, config):
    raise RuntimeError("boom")
'''

EVAL_SPEC = {
    "entry": "solve",
    "entry_doc": "def solve(instance, config) -> list[int]  # 返回选中物品下标",
    "description": "0-1 背包",
    "instance": INSTANCE,
    "judge": JUDGE,
    "judge_entry": "judge",
    "timeout": 8,
}


FENCE_BROKEN = "```python\n" + BROKEN + "\n```"


class ScriptedAdapter(LLMAdapter):
    """按脚本依次返回应答;最后一个应答重复使用。"""

    name = "scripted"

    def __init__(self, replies: list[str]):
        self.replies = list(replies)
        self.calls = 0

    async def chat(self, req):
        text = self.replies[min(self.calls, len(self.replies) - 1)]
        self.calls += 1
        return LLMResponse(text=text, provider=self.name, model=req.model)


def _mount_scripted_llm(app, replies: list[str]) -> ScriptedAdapter:
    adapter = ScriptedAdapter(replies)
    ctx = app.state.ctx
    ctx.llm.register_adapter(adapter)
    ctx.llm.set_fallback_chain(["scripted:mock"])
    return adapter


async def seed_engine_problem(client, admin_headers, key="knap-engine"):
    contract = {"description": "0-1 背包", "evaluate": EVAL_SPEC}
    r = await client.put(f"/api/v2/admin/problems/{key}", headers=admin_headers,
                         json={"name": "背包", "kind": "optimization",
                               "ascend": True, "contract": contract})
    assert r.status_code == 200, r.text


async def test_evolve_engine_improves_and_harvests(client, app, settings):
    """真实循环:弱种子起步 → LLM 变异(含坏候选)→ 方向感知选择 → 收割。"""
    admin = await login_admin(client, settings)
    user = await register_and_login(client, "engine1")
    await seed_engine_problem(client, admin)

    adapter = _mount_scripted_llm(app, [
        f"```python\n{GREEDY}\n```",     # 第 1 次:好候选
        f"```python\n{BROKEN}\n```",     # 第 2 次:坏候选(进失败反馈)
        f"```python\n{GREEDY}\n```",     # 第 3 次:重复目标值(去重)
    ])

    r = await client.post("/api/v2/run", headers=user, json={
        "kind": "evolve_llm", "problem_key": "knap-engine",
        "config": {"num_generations": 2, "population_size": 4,
                   "candidates_per_gen": 2, "seed_code": WEAK_SEED}})
    assert r.status_code == 201, r.text
    assert r.json()["kind"] == "evolve_llm"
    run_id = r.json()["id"]

    done = await wait_run(client, user, run_id, timeout=60)
    assert done["status"] == "completed", done.get("error_message")
    result = done["result"]

    # 弱种子(-50)被 LLM 变异体(-90)超越,方向感知选择生效
    assert result["best_objective"] == -90.0
    assert "def solve" in result["best_heuristic"]["algorithm"]
    # 坏候选由裁判判大罚值(平台语义:非法应答 → 10**9),选择时被淘汰;
    # 重复目标值被去重
    assert result["stats"]["eval_fail"] == 0
    assert result["best_objective"] == -90.0
    assert result["stats"]["llm_calls"] >= 2

    # 每代快照落库,最优单调不回退
    gens = (await client.get(f"/api/v2/runs/{run_id}/generations",
                             headers=user)).json()["generations"]
    assert len(gens) == 2
    bests = [g["best_objective"] for g in gens]
    assert all(b1 >= b2 for b1, b2 in zip(bests, bests[1:]))

    # 收割:方向守卫接受更优个体,种子库入库
    hv = await client.post(f"/api/v2/harvest/{run_id}", headers=user, json={})
    assert hv.status_code == 200 and hv.json()["accepted"] is True
    assert hv.json()["objective"] == -90.0
    seeds = (await client.get("/api/v2/seeds?problem_key=knap-engine",
                              headers=user)).json()["seeds"]
    assert len(seeds) == 1


async def test_evolve_engine_default_kind_via_contract(client, app, settings):
    """契约带 evaluate 规格 → /api/v2/run 省略 kind 时自动选 evolve_llm。"""
    admin = await login_admin(client, settings)
    user = await register_and_login(client, "engine2")
    await seed_engine_problem(client, admin, "knap-auto")
    _mount_scripted_llm(client._transport.app, [f"```python\n{GREEDY}\n```"])

    r = await client.post("/api/v2/run", headers=user, json={
        "problem_key": "knap-auto",
        "config": {"num_generations": 1, "candidates_per_gen": 1,
                   "seed_code": WEAK_SEED}})
    assert r.status_code == 201, r.text
    assert r.json()["kind"] == "evolve_llm"
    done = await wait_run(client, user, r.json()["id"], timeout=60)
    assert done["status"] == "completed", done.get("error_message")
    assert done["result"]["best_objective"] == -90.0


async def test_engine_requires_judge_contract(client, settings):
    """契约缺 judge → 结构化报错,而非运行中途失败。"""
    admin = await login_admin(client, settings)
    user = await register_and_login(client, "engine3")
    r = await client.put("/api/v2/admin/problems/nojudge", headers=admin,
                         json={"name": "无裁判", "kind": "optimization"})
    assert r.status_code == 200
    r = await client.post("/api/v2/run", headers=user, json={
        "kind": "evolve_llm", "problem_key": "nojudge",
        "config": {"num_generations": 1}})
    assert r.status_code == 201  # 入队成功,执行时结构化失败
    done = await wait_run(client, user, r.json()["id"], timeout=30)
    assert done["status"] == "failed"
    assert done["error_code"] == "INVALID_INPUT"


async def test_compat_start_uses_engine_for_contract_problems(client, app, settings):
    admin = await login_admin(client, settings)
    user = await register_and_login(client, "engine4")
    await seed_engine_problem(client, admin, "knap-compat")
    _mount_scripted_llm(client._transport.app, [f"```python\n{GREEDY}\n```"])

    r = await client.post("/api/evolution/start", headers=user, json={
        "problem_key": "knap-compat", "num_generations": 1, "ascend": True,
        "population_size": 4, "candidates_per_gen": 1})
    assert r.status_code == 200, r.text
    run_id = r.json()["run_id"]
    run = (await client.get(f"/api/v2/runs/{run_id}", headers=user)).json()
    assert run["kind"] == "evolve_llm"
    assert run["config"]["seed_code"] is None  # 兼容载荷无 framework_code
    done = await wait_run(client, user, run_id, timeout=60)
    # 无种子纯 LLM 起步也应完成
    assert done["status"] == "completed", done.get("error_message")


async def test_repair_loop_recovers_parse_failure(client, app, settings):
    """修复回路(机制 #15):解析失败带原始输出喂回重试,第二次成功。"""
    admin = await login_admin(client, settings)
    user = await register_and_login(client, "repair1")
    await seed_engine_problem(client, admin, "knap-repair")

    adapter = _mount_scripted_llm(app, [
        "抱歉,我无法输出代码。",                      # 第 1 次:不可解析
        f"```python\n{GREEDY}\n```",                  # 修复重试:合法
    ])
    r = await client.post("/api/v2/run", headers=user, json={
        "kind": "evolve_llm", "problem_key": "knap-repair",
        "config": {"num_generations": 1, "candidates_per_gen": 1,
                   "llm_repair_attempts": 1}})
    assert r.status_code == 201, r.text
    done = await wait_run(client, user, r.json()["id"], timeout=30)
    assert done["status"] == "completed", done.get("error_message")
    result = done["result"]
    assert result["best_objective"] == -90.0        # 修复后的候选被采纳
    assert result["stats"]["llm_calls"] == 2        # 实际调用计数(不再翻倍)


async def test_penalty_candidates_never_enter_population(client, app, settings):
    """回归(run 5 发现):裁判罚值个体曾被保留在种群与快照里,必须淘汰。"""
    admin = await login_admin(client, settings)
    user = await register_and_login(client, "pen1")
    await seed_engine_problem(client, admin, "knap-pen")
    _mount_scripted_llm(app, [FENCE_BROKEN])  # 恒产罚值候选

    r = await client.post("/api/v2/run", headers=user, json={
        "kind": "evolve_llm", "problem_key": "knap-pen",
        "config": {"num_generations": 2, "candidates_per_gen": 1,
                   "population_size": 4, "seed_code": WEAK_SEED}})
    run_id = r.json()["id"]
    done = await wait_run(client, user, run_id, timeout=30)
    assert done["status"] == "completed", done.get("error_message")

    gens = (await client.get(f"/api/v2/runs/{run_id}/generations",
                             headers=user)).json()["generations"]
    for g in gens:
        for ind in g["snapshot"]["individuals"]:
            assert abs(ind["objective"]) < 10**9, g["snapshot"]
    # 种子(合法)保底,罚值候选被淘汰
    assert done["best_objective"] == -50.0
    assert done["result"]["stats"]["population"] == 1
