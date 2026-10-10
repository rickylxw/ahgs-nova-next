# -*- coding: utf-8 -*-
"""内建契约题:裁判驱动评测 + 引擎端到端 + 非法应答判罚。"""
from __future__ import annotations

import pytest

from app.contracts.builtin import CONTRACTS, PENALTY
from app.services.evaluators import evaluate_solution

from .conftest import login_admin, register_and_login, wait_run

# 五题的合法流式贪心候选(最小接口实现,兼作文档)
LEGAL_CANDS = {
    "knapsack": "def select_item(i, rem, w, v, n):\n    return 1 if w[i] <= rem else 0\n",
    "maxcut": ("import numpy as np\n"
               "def assign_node(node, un, A, part):\n"
               "    s1 = sum(A[node][u] for u in range(len(part)) if part[u] == 1)\n"
               "    s0 = sum(A[node][u] for u in range(len(part)) if part[u] == 0)\n"
               "    return 1 if s1 >= s0 else 0\n"),
    "binpacking": ("def place_item(size, rems, sizes, n):\n"
                   "    for k in range(len(rems)):\n"
                   "        if rems[k] >= size - 1e-9:\n"
                   "            return k\n"
                   "    return -1\n"),
    "graphcoloring": ("def choose_color(node, A, cols, k):\n"
                      "    used = {int(cols[u]) for u in range(len(cols)) if cols[u] >= 0 and A[node][u] > 0}\n"
                      "    for c in range(k):\n"
                      "        if c not in used:\n"
                      "            return c\n"
                      "    return k\n"),
    "tsp": ("def select_next_node(cur, dst, un, D):\n"
            "    un = list(un)\n"
            "    return min(un, key=lambda x: (D[cur][x], x))\n"),
    "cvrp": ("import numpy as np\n"
             "def find_best_route(cur, rem, cap, load, D, dem):\n"
             "    best, bd = -1, 1e18\n"
             "    for v in range(1, len(rem)):\n"
             "        if rem[v] and load + dem[v] <= cap + 1e-9 and D[cur][v] < bd:\n"
             "            best, bd = v, D[cur][v]\n"
             "    return best\n"),
    "mtsp": ("def select_next_node(cur, un, D, rem):\n"
             "    un = list(un)\n"
             "    return min(un, key=lambda x: (D[cur][x], x)) if len(un) else -1\n"),
    "vrptw": ("import numpy as np\n"
              "def select_next_customer(cur, t, rem, cap, load, D, dem, tw, st):\n"
              "    best, bd = -1, 1e18\n"
              "    for v in range(1, len(rem)):\n"
              "        if rem[v] and load + dem[v] <= cap + 1e-9 and t + D[cur][v] <= tw[v][1] + 1e-9:\n"
              "            if tw[v][1] < bd:\n"
              "                best, bd = v, tw[v][1]\n"
              "    return best\n"),
    "orienteering": ("def select_next_node(cur, vis, profit, D, left, got):\n"
                     "    best, bs = -1, 0.0\n"
                     "    for v in range(1, len(profit)):\n"
                     "        if not vis[v] and profit[v] > 0:\n"
                     "            need = D[cur][v] + D[v][0]\n"
                     "            if need <= left + 1e-9 and profit[v] / max(need, 1e-9) > bs:\n"
                     "                best, bs = v, profit[v] / max(need, 1e-9)\n"
                     "    return best\n"),
    "setcover": ("import numpy as np\n"
                 "def select_next_set(unc, M, costs):\n"
                 "    gains = (unc & M).sum(axis=1)\n"
                 "    if not gains.any():\n"
                 "        return None\n"
                 "    return int(np.argmin(np.where(gains > 0, costs / np.maximum(gains, 1e-9), np.inf)))\n"),
    "vertexcover": ("import numpy as np\n"
                    "def select_next_vertex(unc, A, cover):\n"
                    "    if not unc.any():\n"
                    "        return None\n"
                    "    return int(np.argmax(unc.sum(axis=1) * (~cover)))\n"),
    "maxclique": ("def select_next_vertex(clique, cand, A):\n"
                  "    return cand[0] if cand else None\n"),
    "kcenter": ("def select_next_center(sel, cand, D, k):\n"
                "    if not cand:\n"
                "        return None\n"
                "    n = len(D)\n"
                "    def rad(c):\n"
                "        s = sel + [c]\n"
                "        return max(min(D[i][x] for x in s) for i in range(n))\n"
                "    return min(cand, key=rad)\n"),
    "steinertree": ("import numpy as np\n"
                    "def select_next_terminal(tree, unconn, D, SP):\n"
                    "    tnodes = [i for i in range(len(tree)) if tree[i]]\n"
                    "    return min(list(unconn), key=lambda v: min(SP[u][v] for u in tnodes))\n"),
    "partition": ("def assign_number(i, a, b, nums):\n"
                  "    return 0 if a <= b else 1\n"),
    "pfsp": ("import numpy as np\n"
             "def select_next_job(uns, sched, P, m):\n"
             "    best, bd = None, 1e18\n"
             "    for j in uns:\n"
             "        ready = [0.0] * m\n"
             "        for jj in list(sched) + [int(j)]:\n"
             "            t = 0.0\n"
             "            for k in range(m):\n"
             "                t = max(t, ready[k]) + P[jj][k]\n"
             "                ready[k] = t\n"
             "        if ready[-1] < bd:\n"
             "            best, bd = int(j), ready[-1]\n"
             "    return best\n"),
    "jsp": ("import numpy as np\n"
            "def select_next_job(avail, prog, T, ready_m, M):\n"
            "    best, bd = None, 1e18\n"
            "    for j in avail:\n"
            "        j = int(j); k = int(prog[j]); mach = int(M[j][k])\n"
            "        end = max(ready_m[mach], 0.0) + T[j][k]\n"
            "        if end < bd:\n"
            "            best, bd = j, end\n"
            "    return best\n"),
    "smtwt": ("import numpy as np\n"
              "def select_next_job(uns, t, p, d, w):\n"
              "    best, bs = None, 1e18\n"
              "    for j in uns:\n"
              "        j = int(j)\n"
              "        score = w[j] * max(0.0, t + p[j] - d[j]) / p[j]\n"
              "        if score < bs:\n"
              "            best, bs = j, score\n"
              "    return best\n"),
    "parmachine": ("import numpy as np\n"
                   "def assign_job(j, loads, p, m):\n"
                   "    return int(np.argmin(loads))\n"),
    "qap": ("import numpy as np\n"
            "def assign_facility(f, avail, F, D, assign):\n"
            "    placed = [(i, x) for i, x in enumerate(assign) if x >= 0]\n"
            "    def cost(x):\n"
            "        return sum(F[f][i] * D[x][xi] for i, xi in placed)\n"
            "    return min(avail, key=cost)\n"),
    "power_trading": ("def propose_target_mwh(t, l10, l50, l90, p10, p50, p90, ll, lp, pos, fee):\n"
                      "    if p50 + fee < lp:\n"
                      "        return ll\n"
                      "    if p50 - fee > lp:\n"
                      "        return min(pos, l50)\n"
                      "    return pos\n"),
}

# knapsack 的更差候选:什么都不拿 → 剩余容量最大
LAZY_KNAPSACK = "def select_item(i, rem, w, v, n):\n    return 0\n"

ILLEGAL_KNAPSACK = "def select_item(i, rem, w, v, n):\n    return 2\n"


@pytest.mark.parametrize("key", sorted(CONTRACTS))
async def test_builtin_contract_judges_legal_candidate(key):
    spec = CONTRACTS[key]["evaluate"]
    for inst in (spec["instance"], spec["prescreen_instance"]):
        out = await evaluate_solution(
            LEGAL_CANDS[key], judge_source=spec["judge"],
            judge_entry=spec["judge_entry"], entry=spec["entry"],
            instance=inst, timeout=spec["timeout"])
        assert out.ok, (key, out.as_dict())
        assert out.objective < PENALTY


async def test_builtin_contract_penalizes_illegal():
    spec = CONTRACTS["knapsack"]["evaluate"]
    out = await evaluate_solution(
        ILLEGAL_KNAPSACK, judge_source=spec["judge"], entry=spec["entry"],
        instance=spec["instance"], timeout=spec["timeout"])
    assert out.ok and out.objective == PENALTY  # 平台语义:非法应答判 inf


async def test_builtin_contract_missing_entry():
    spec = CONTRACTS["knapsack"]["evaluate"]
    out = await evaluate_solution(
        "def other(): pass", judge_source=spec["judge"], entry=spec["entry"],
        instance=spec["instance"], timeout=spec["timeout"])
    assert not out.ok and out.fail_reason == "bad_entry"


async def _register_builtin_problem(client, admin, key):
    from app.contracts.builtin import CONTRACTS as C

    spec = C[key]
    r = await client.put(f"/api/v2/admin/problems/{key}", headers=admin, json={
        "name": spec["name"], "kind": "optimization", "ascend": spec["ascend"],
        "contract": {"description": spec["description"],
                     "evaluate": spec["evaluate"]}})
    assert r.status_code == 200, r.text


class ScriptedAdapter:
    from app.services.llm import LLMAdapter  # noqa: F401

    name = "scripted2"

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    async def chat(self, req):
        from app.services.llm import LLMResponse

        text = self.replies[min(self.calls, len(self.replies) - 1)]
        self.calls += 1
        return LLMResponse(text=text, provider=self.name, model=req.model)


async def test_evolve_on_builtin_knapsack_end_to_end(client, app, settings):
    """内建契约 × 引擎端到端:好种子保底,差候选被方向感知淘汰,收割入库。"""
    from app.services.llm import LLMResponse  # noqa: F401

    admin = await login_admin(client, settings)
    user = await register_and_login(client, "builtin1")
    await _register_builtin_problem(client, admin, "knapsack")

    adapter = ScriptedAdapter([f"```python\n{LAZY_KNAPSACK}\n```"])
    ctx = app.state.ctx
    ctx.llm.register_adapter(adapter)
    ctx.llm.set_fallback_chain(["scripted2:mock"])

    r = await client.post("/api/v2/run", headers=user, json={
        "problem_key": "knapsack",   # kind 省略:契约带 evaluate → evolve_llm
        "config": {"num_generations": 2, "population_size": 4,
                   "candidates_per_gen": 1, "seed_code": LEGAL_CANDS["knapsack"],
                   "seed_concept": "greedy take"}})
    assert r.status_code == 201, r.text
    assert r.json()["kind"] == "evolve_llm"
    run_id = r.json()["id"]

    done = await wait_run(client, user, run_id, timeout=60)
    assert done["status"] == "completed", done.get("error_message")
    result = done["result"]
    # 贪心(拿得越多剩得越少)优于全不拿:种子保底
    assert result["best_objective"] < PENALTY
    gens = (await client.get(f"/api/v2/runs/{run_id}/generations",
                             headers=user)).json()["generations"]
    assert len(gens) == 2

    hv = await client.post(f"/api/v2/harvest/{run_id}", headers=user, json={})
    assert hv.status_code == 200 and hv.json()["accepted"] is True
