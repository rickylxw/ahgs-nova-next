# -*- coding: utf-8 -*-
"""官方兼容层补全:developer 路由 / custom-problems / Agent 建题 / prompt 注入。"""
from __future__ import annotations

import json

from app.services.llm import LLMAdapter, LLMResponse

from .conftest import (
    login_admin, make_settings, register_and_login, seed_problem, wait_run,
)


class Scripted(LLMAdapter):
    name = "scripted-official"

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    async def chat(self, req):
        text = self.replies[min(self.calls, len(self.replies) - 1)]
        self.calls += 1
        return LLMResponse(text=text, provider=self.name, model=req.model)


async def test_my_runs_includes_evolve_llm(client, settings):
    """回归:NOVA 进化记录看不到自己发起的运行 —— /api/evolution/my 漏了 evolve_llm。"""
    admin = await login_admin(client, settings)
    user = await register_and_login(client, "myruns1")
    await seed_problem(client, admin, "nojudge")
    r = await client.post("/api/v2/run", headers=user, json={
        "kind": "evolve_llm", "problem_key": "nojudge",
        "config": {"num_generations": 1, "candidates_per_gen": 1}})
    assert r.status_code == 201, r.text
    await wait_run(client, user, r.json()["id"], timeout=30)  # failed 也应在记录里

    my = (await client.get("/api/evolution/my", headers=user)).json()["runs"]
    assert any(x["id"] == r.json()["id"] for x in my)
    assert any(x["kind"] == "evolve_llm" for x in my)


async def test_developer_validate_upload_run_flow(client, settings):
    admin = await login_admin(client, settings)
    user = await register_and_login(client, "dev1")
    await seed_problem(client, admin, "dev-p")

    # 校验:合法 / 语法错误
    ok = await client.post("/api/developer/validate", headers=user, json={
        "framework_code": "def select_item(i, rem, w, v, n):\n    return 0\n"})
    assert ok.status_code == 200 and ok.json()["valid"] is True
    bad = await client.post("/api/developer/validate", headers=user, json={
        "framework_code": "def broken(:\n"})
    assert bad.status_code == 200 and bad.json()["valid"] is False

    # 上传 → framework_id(内容寻址)
    code = "def select_item(i, rem, w, v, n):\n    return 1 if w[i] <= rem else 0\n"
    up = await client.post("/api/developer/upload", headers=user, json={
        "framework_code": code, "framework_filename": "framework.py"})
    assert up.status_code == 200, up.text
    fid = up.json()["framework_id"]

    # 上传同样内容 → 幂等同 id
    up2 = await client.post("/api/developer/upload", headers=user, json={
        "framework_code": code})
    assert up2.json()["framework_id"] == fid

    # developer/run:framework_id 反查源码作为种子,启动本地引擎
    r = await client.post("/api/developer/run", headers=user, json={
        "problem_key": "dev-p", "framework_id": fid,
        "num_generations": 1, "ascend": True})
    assert r.status_code == 200, r.text
    run_id = r.json()["run_id"]
    run = (await client.get(f"/api/v2/runs/{run_id}", headers=user)).json()
    assert run["kind"] == "evolve_local"  # dev-p 无 evaluate 契约 → 演示执行器
    assert run["config"]["seed_code"] == code


async def test_custom_problems_upload_list_delete(client, settings):
    user = await register_and_login(client, "cust1")

    r = await client.post("/api/custom-problems/upload", headers=user,
                          files={"files": ("evaluator.py",
                                           b"def evaluate(instance):\n    return 0\n",
                                           "text/plain")})
    assert r.status_code == 200, r.text
    key = r.json()["key"]
    assert r.json()["files"] == ["evaluator.py"]

    lst = (await client.get("/api/custom-problems", headers=user)).json()
    match = [x for x in lst if x["key"] == key]
    assert match and match[0]["name"] == "evaluator"
    assert match[0]["has_engine"] is False  # 未建题,引擎不可跑

    got = (await client.get(f"/api/custom-problems/{key}", headers=user)).json()
    assert got["key"] == key

    d = await client.delete(f"/api/custom-problems/{key}", headers=user)
    assert d.status_code == 200
    lst2 = (await client.get("/api/custom-problems", headers=user)).json()
    assert not [x for x in lst2 if x["key"] == key]


async def test_agent_build_problem_end_to_end(client, app, settings):
    """Agent 建题:plan(LLM 出题纲)→ execute(LLM 生成裁判,冒烟校验)→ 注册契约。"""
    admin = await login_admin(client, settings)
    user = await register_and_login(client, "agent1")

    plan_json = json.dumps({
        "entry": "solve",
        "entry_doc": "def solve(instance, config) -> float  # 越接近 0 越好",
        "description": "平方和最小化演示题",
        "scoring": "objective = sum(x^2),越小越好",
        "instance": {"x": [3, 4]},
    }, ensure_ascii=False)
    judge_src = (
        "def judge(instance, config, ns):\n"
        "    try:\n"
        "        v = ns['solve'](instance, config)\n"
        "        return 10**9\n"
        "    except Exception:\n"
        "        return 10**9\n")
    judge_json = json.dumps({
        "judge": judge_src,
        "instance": {"x": [3, 4]},
        "prescreen_instance": {"x": [3]},
    }, ensure_ascii=False)

    app.state.ctx.llm.register_adapter(Scripted([plan_json, judge_json]))
    app.state.ctx.llm.set_fallback_chain(["scripted-official:mock"])

    plan = await client.post("/api/custom-problems/agent/plan", headers=user,
                             json={"name": "平方和", "description": "演示"})
    assert plan.status_code == 200, plan.text
    plan_id = plan.json()["plan_id"]

    ex = await client.post("/api/custom-problems/agent/execute", headers=user,
                           json={"plan_id": plan_id})
    assert ex.status_code == 200, ex.text
    run_id = ex.json()["run_id"]

    import asyncio
    deadline = asyncio.get_event_loop().time() + 20
    state = {}
    while asyncio.get_event_loop().time() < deadline:
        state = (await client.get(
            f"/api/custom-problems/agent/runs/{run_id}", headers=user)).json()
        if state["status"] in ("completed", "failed"):
            break
        await asyncio.sleep(0.2)
    assert state["status"] == "completed", state
    assert state["problem_key"]

    lst = (await client.get("/api/custom-problems", headers=user)).json()
    match = [x for x in lst if x["key"] == state["problem_key"]]
    assert match and match[0]["has_engine"] is True


async def test_prompt_override_stored(client, settings):
    admin = await login_admin(client, settings)
    user = await register_and_login(client, "prompt1")
    await seed_problem(client, admin, "prompt-p")

    r = await client.post("/api/evolution/start", headers=user, json={
        "problem_key": "prompt-p", "num_generations": 1})
    run_id = r.json()["run_id"]

    p = await client.post(f"/api/evolution/{run_id}/prompt", headers=user,
                          json={"prompt": "优先尝试模拟退火思路。"})
    assert p.status_code == 200
    got = (await client.get(f"/api/evolution/{run_id}/prompt",
                            headers=user)).json()
    assert got["prompt"] == "优先尝试模拟退火思路。"
    run = (await client.get(f"/api/v2/runs/{run_id}", headers=user)).json()
    assert run["config"]["llm_prompt_override"] == "优先尝试模拟退火思路。"
