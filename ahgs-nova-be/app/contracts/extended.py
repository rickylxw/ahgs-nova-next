# -*- coding: utf-8 -*-
"""扩展题目契约:其余 16 题的判定程序(流式驱动移植自 _prescreen_specs.py)。

与 builtin.py 的五题同一约定:
- judge(instance, config, ns) 裁判驱动;违规/异常 → 10**9 罚值;
- 实例由 seed 确定性生成;prescreen_instance 为迷你版;
- 目标值按官方描述取自然极小化变换(power_trading 例外,官方 ascend=False,
  按描述取"相对被动基线的成本节省率",越大越好);
- parmachine 的越界机器索引判罚值 —— 即冲榜记录 §8.3 疑似被利用的语义漏洞,
  在本裁判中显式堵死。
"""
from __future__ import annotations

PENALTY = 10 ** 9

# ---------------------------------------------------------------- cvrp

_CVRP_JUDGE = '''
import numpy as np

def judge(instance, config, ns):
    """流式驱动 find_best_route(-1=回仓库);objective = 总行驶距离。"""
    fn = ns["find_best_route"]
    rng = np.random.default_rng(int(instance.get("seed", 7)))
    n = int(instance.get("n", 21))
    D = rng.integers(2, 40, (n, n)).astype(float)
    D = (D + D.T) / 2
    np.fill_diagonal(D, 0.0)
    dem = np.zeros(n)
    dem[1:] = rng.integers(1, 10, n - 1)
    cap = float(instance.get("cap", 25))
    served = np.zeros(n, dtype=bool)
    cur, load, dist = 0, 0.0, 0.0
    guard = 0
    while not served[1:].all():
        guard += 1
        if guard > 3 * n:
            return 10**9
        try:
            nxt = int(fn(cur, ~served, cap, load, D, dem))
        except Exception:
            return 10**9
        if nxt == -1:
            dist += D[cur, 0]
            cur, load = 0, 0.0
            continue
        if not (1 <= nxt < n and not served[nxt] and load + dem[nxt] <= cap + 1e-6):
            return 10**9
        dist += D[cur, nxt]
        load += dem[nxt]
        served[nxt] = True
        cur = nxt
    return float(dist + D[cur, 0])
'''

# ---------------------------------------------------------------- mtsp

_MTSP_JUDGE = '''
import numpy as np

def judge(instance, config, ns):
    """流式驱动 select_next_node(-1=换销售员);objective = 总行驶距离。"""
    fn = ns["select_next_node"]
    rng = np.random.default_rng(int(instance.get("seed", 7)))
    n = int(instance.get("n", 32))
    m = int(instance.get("m", 4))
    D = rng.integers(2, 40, (n, n)).astype(float)
    D = (D + D.T) / 2
    np.fill_diagonal(D, 0.0)
    un = set(range(1, n))
    cur, rem, dist = 0, m, 0.0
    guard = 0
    while un:
        guard += 1
        if guard > 3 * n:
            return 10**9
        try:
            nxt = int(fn(cur, np.array(sorted(un)), D, rem))
        except Exception:
            return 10**9
        if nxt == -1:
            dist += D[cur, 0]
            rem -= 1
            cur = 0
            if rem < 1:
                return 10**9
            continue
        if nxt not in un:
            return 10**9
        dist += D[cur, nxt]
        un.discard(nxt)
        cur = nxt
    return float(dist + D[cur, 0])
'''

# ---------------------------------------------------------------- vrptw

_VRPTW_JUDGE = '''
import numpy as np

def judge(instance, config, ns):
    """流式驱动 select_next_customer(-1=回仓);objective = 总行驶距离(时间窗/容量违约判罚)。"""
    fn = ns["select_next_customer"]
    rng = np.random.default_rng(int(instance.get("seed", 7)))
    n = int(instance.get("n", 16))
    D = rng.integers(2, 30, (n, n)).astype(float)
    D = (D + D.T) / 2
    np.fill_diagonal(D, 0.0)
    dem = np.zeros(n)
    dem[1:] = rng.integers(2, 8, n - 1)
    cap = float(instance.get("cap", 20))
    tw = np.zeros((n, 2))
    tw[1:, 0] = rng.integers(0, 40, n - 1)
    # 窗口放宽到 300-600:纯 CPU 策略的合理路线也能全部满足,时间压力仍可判罚死锁
    tw[1:, 1] = tw[1:, 0] + rng.integers(300, 600, n - 1)
    tw[0] = [0, 10_000]
    st = np.zeros(n)
    st[1:] = 2.0
    served = np.zeros(n, dtype=bool)
    cur, t, load, dist = 0, 0.0, 0.0, 0.0
    guard = 0
    while not served[1:].all():
        guard += 1
        if guard > 3 * n:
            return 10**9
        try:
            nxt = int(fn(cur, t, ~served, cap, load, D, dem, tw, st))
        except Exception:
            return 10**9
        if nxt == -1:
            t += D[cur, 0]
            dist += D[cur, 0]
            cur, load = 0, 0.0
            continue
        arrival = t + D[cur, nxt]
        if not (1 <= nxt < n and not served[nxt]
                and arrival <= tw[nxt, 1] + 1e-6
                and load + dem[nxt] <= cap + 1e-6):
            return 10**9
        t = max(arrival, tw[nxt, 0]) + st[nxt]
        dist += D[cur, nxt]
        load += dem[nxt]
        served[nxt] = True
        cur = nxt
    return float(dist)
'''

# ---------------------------------------------------------------- orienteering

_ORIENTEERING_JUDGE = '''
import numpy as np

def judge(instance, config, ns):
    """流式驱动 select_next_node(-1=结束);objective = -已获利润(预算内越多人越好)。"""
    fn = ns["select_next_node"]
    rng = np.random.default_rng(int(instance.get("seed", 7)))
    n = int(instance.get("n", 25))
    D = rng.integers(2, 30, (n, n)).astype(float)
    D = (D + D.T) / 2
    np.fill_diagonal(D, 0.0)
    profit = np.zeros(n)
    profit[1:] = rng.integers(1, 10, n - 1)
    budget = float(instance.get("budget_mult", 5)) * float(D.sum() / n)
    visited = np.zeros(n, dtype=bool)
    cur, left, got = 0, budget, 0.0
    guard = 0
    while True:
        guard += 1
        if guard > 3 * n:
            return 10**9
        try:
            nxt = int(fn(cur, visited, profit, D, left, got))
        except Exception:
            return 10**9
        if nxt == -1:
            if D[cur, 0] > left + 1e-6:
                return 10**9
            break
        if not (1 <= nxt < n and not visited[nxt]
                and D[cur, nxt] + D[nxt, 0] <= left + 1e-6):
            return 10**9
        left -= D[cur, nxt]
        got += profit[nxt]
        visited[nxt] = True
        cur = nxt
    return float(-got)
'''

# ---------------------------------------------------------------- setcover

_SETCOVER_JUDGE = '''
import numpy as np

def judge(instance, config, ns):
    """流式驱动 select_next_set(None=结束);objective = 选用集总成本(未覆盖完判罚)。"""
    fn = ns["select_next_set"]
    rng = np.random.default_rng(int(instance.get("seed", 7)))
    n_elem = int(instance.get("n_elem", 60))
    n_sets = int(instance.get("n_sets", 25))
    M = rng.random((n_sets, n_elem)) < 0.2
    for e in range(n_elem):
        M[rng.integers(0, n_sets), e] = True
    costs = rng.integers(1, 10, n_sets).astype(float)
    uncovered = np.ones(n_elem, dtype=bool)
    total = 0.0
    guard = 0
    while uncovered.any():
        guard += 1
        if guard > n_sets + 2:
            return 10**9
        try:
            s = fn(uncovered, M, costs)
            s = int(s)
        except Exception:
            return 10**9
        if not (0 <= s < n_sets):
            return 10**9
        total += costs[s]
        uncovered &= ~M[s]
    return float(total)
'''

# ---------------------------------------------------------------- vertexcover

_VERTEXCOVER_JUDGE = '''
import numpy as np

def judge(instance, config, ns):
    """流式驱动 select_next_vertex(None=结束);objective = 覆盖集大小(有边残留判罚)。"""
    fn = ns["select_next_vertex"]
    rng = np.random.default_rng(int(instance.get("seed", 7)))
    n = int(instance.get("n", 30))
    A = np.zeros((n, n))
    mask = np.triu(rng.random((n, n)) < 0.15, 1)
    A[mask] = 1
    A = A + A.T
    unc = A > 0
    cover = np.zeros(n, dtype=bool)
    guard = 0
    while unc.any():
        guard += 1
        if guard > n + 2:
            return 10**9
        try:
            v = fn(unc, A, cover)
            v = int(v)
        except Exception:
            return 10**9
        if not (0 <= v < n) or cover[v]:
            return 10**9
        cover[v] = True
        unc[v, :] = False
        unc[:, v] = False
    return float(cover.sum())
'''

# ---------------------------------------------------------------- maxclique

_MAXCLIQUE_JUDGE = '''
import numpy as np

def judge(instance, config, ns):
    """流式驱动 select_next_vertex(None=结束);objective = -团大小(越大团越好)。"""
    fn = ns["select_next_vertex"]
    rng = np.random.default_rng(int(instance.get("seed", 7)))
    n = int(instance.get("n", 30))
    A = np.zeros((n, n))
    mask = np.triu(rng.random((n, n)) < 0.5, 1)
    A[mask] = 1
    A = A + A.T
    clique = []
    guard = 0
    while True:
        guard += 1
        if guard > n + 2:
            return 10**9
        cand = [v for v in range(n) if v not in clique
                and all(A[v, u] > 0 for u in clique)]
        try:
            v = fn(list(clique), cand, A)
        except Exception:
            return 10**9
        if v is None:
            break
        v = int(v)
        if v not in cand:
            return 10**9
        clique.append(v)
    return float(-len(clique))
'''

# ---------------------------------------------------------------- kcenter

_KCENTER_JUDGE = '''
import numpy as np

def judge(instance, config, ns):
    """流式驱动 select_next_center(None=提前停);objective = 覆盖半径(最大最近中心距)。"""
    fn = ns["select_next_center"]
    rng = np.random.default_rng(int(instance.get("seed", 7)))
    n = int(instance.get("n", 30))
    k = int(instance.get("k", 4))
    D = rng.integers(1, 50, (n, n)).astype(float)
    D = (D + D.T) / 2
    np.fill_diagonal(D, 0.0)
    selected = []
    guard = 0
    while len(selected) < k:
        guard += 1
        if guard > k + 2:
            return 10**9
        try:
            c = fn(list(selected), [i for i in range(n) if i not in selected], D, k)
        except Exception:
            return 10**9
        if c is None:
            break
        c = int(c)
        if c in selected:
            return 10**9
        selected.append(c)
    if not selected:
        return 10**9
    radius = max(min(D[i, c] for c in selected) for i in range(n))
    return float(radius)
'''

# ---------------------------------------------------------------- steinertree

_STEINERTREE_JUDGE = '''
import numpy as np

def judge(instance, config, ns):
    """流式驱动 select_next_terminal(None=结束);裁判沿最短路径接入终端。
    objective = 生成树总权(按最短路度量累加,路径重叠不扣减 —— 自洽近似)。"""
    fn = ns["select_next_terminal"]
    rng = np.random.default_rng(int(instance.get("seed", 7)))
    n = int(instance.get("n", 20))
    n_terms = int(instance.get("n_terms", 4))
    D = rng.integers(1, 40, (n, n)).astype(float)
    D = (D + D.T) / 2
    np.fill_diagonal(D, 0.0)
    SP = D.copy()
    for w in range(n):
        SP = np.minimum(SP, SP[:, [w]] + SP[[w], :])
    terms = sorted(rng.choice(n, n_terms, replace=False).tolist())
    tree = [terms[0]]
    unconn = terms[1:]
    weight = 0.0
    guard = 0
    while unconn:
        guard += 1
        if guard > len(terms) + 2:
            return 10**9
        try:
            v = fn(np.isin(np.arange(n), tree), np.array(unconn), D, SP)
        except Exception:
            return 10**9
        if v is None:
            return 10**9
        v = int(v)
        if v not in unconn:
            return 10**9
        weight += float(min(SP[u, v] for u in tree))
        unconn.remove(v)
        tree.append(v)
    return float(weight)
'''

# ---------------------------------------------------------------- partition

_PARTITION_JUDGE = '''
import numpy as np

def judge(instance, config, ns):
    """流式驱动 assign_number(0/1 分组);objective = |组A - 组B|。"""
    fn = ns["assign_number"]
    rng = np.random.default_rng(int(instance.get("seed", 7)))
    nums = rng.integers(1, 100, int(instance.get("n", 30))).astype(float)
    a = b = 0.0
    for i in range(len(nums)):
        try:
            g = int(fn(i, a, b, nums))
        except Exception:
            return 10**9
        if g not in (0, 1):
            return 10**9
        if g == 0:
            a += nums[i]
        else:
            b += nums[i]
    return float(abs(a - b))
'''

# ---------------------------------------------------------------- pfsp

_PFSP_JUDGE = '''
import numpy as np

def judge(instance, config, ns):
    """流式驱动 select_next_job;objective = 流水车间 makespan(逐机器链式递推)。"""
    fn = ns["select_next_job"]
    rng = np.random.default_rng(int(instance.get("seed", 7)))
    n = int(instance.get("n", 10))
    m = int(instance.get("m", 3))
    P = rng.integers(1, 20, (n, m)).astype(float)
    sched = []
    for _ in range(n):
        uns = np.array([j for j in range(n) if j not in sched])
        try:
            j = int(fn(uns, list(sched), P, m))
        except Exception:
            return 10**9
        if j not in uns:
            return 10**9
        sched.append(j)
    ready = [0.0] * m
    for j in sched:
        t = 0.0
        for k in range(m):
            t = max(t, ready[k]) + P[j, k]
            ready[k] = t
    return float(ready[-1])
'''

# ---------------------------------------------------------------- jsp

_JSP_JUDGE = '''
import numpy as np

def judge(instance, config, ns):
    """流式驱动 select_next_job(非延迟调度);objective = makespan。"""
    fn = ns["select_next_job"]
    rng = np.random.default_rng(int(instance.get("seed", 7)))
    n = int(instance.get("n", 5))
    ops = int(instance.get("ops", 3))
    m = int(instance.get("m", 3))
    T = rng.integers(1, 10, (n, ops)).astype(float)
    M = rng.integers(0, m, (n, ops))
    ready_m = np.zeros(m)
    ready_j = np.zeros(n)
    prog = np.zeros(n, dtype=int)
    for _ in range(n * ops):
        avail = np.array([j for j in range(n) if prog[j] < ops])
        try:
            j = int(fn(avail, prog, T, ready_m, M))
        except Exception:
            return 10**9
        if j not in avail:
            return 10**9
        k = int(prog[j])
        mach = int(M[j, k])
        end = max(ready_m[mach], ready_j[j]) + T[j, k]
        ready_m[mach] = ready_j[j] = end
        prog[j] += 1
    return float(ready_m.max())
'''

# ---------------------------------------------------------------- smtwt

_SMTWT_JUDGE = '''
import numpy as np

def judge(instance, config, ns):
    """流式驱动 select_next_job;objective = 总加权拖期 Σ w·max(0, C-d)。"""
    fn = ns["select_next_job"]
    rng = np.random.default_rng(int(instance.get("seed", 7)))
    n = int(instance.get("n", 15))
    p = rng.integers(1, 15, n).astype(float)
    d = rng.uniform(0.3, 1.2, n) * p.sum()
    w = rng.integers(1, 5, n).astype(float)
    t = 0.0
    total = 0.0
    done = set()
    for _ in range(n):
        uns = np.array([j for j in range(n) if j not in done])
        try:
            j = int(fn(uns, t, p, d, w))
        except Exception:
            return 10**9
        if j not in uns:
            return 10**9
        t += p[j]
        total += w[j] * max(0.0, t - d[j])
        done.add(j)
    return float(total)
'''

# ---------------------------------------------------------------- parmachine

_PARMACHINE_JUDGE = '''
import numpy as np

def judge(instance, config, ns):
    """流式驱动 assign_job;objective = makespan(机器负载峰值)。
    越界机器索引判罚值 —— 堵死"部分作业不计负载"的语义漏洞(冲榜记录 §8.3)。"""
    fn = ns["assign_job"]
    rng = np.random.default_rng(int(instance.get("seed", 7)))
    n = int(instance.get("n", 25))
    m = int(instance.get("m", 4))
    p = rng.integers(1, 30, n).astype(float)
    loads = np.zeros(m)
    for j in range(n):
        try:
            k = int(fn(j, loads, p, m))
        except Exception:
            return 10**9
        if not (0 <= k < m):
            return 10**9
        loads[k] += p[j]
    return float(loads.max())
'''

# ---------------------------------------------------------------- qap

_QAP_JUDGE = '''
import numpy as np

def judge(instance, config, ns):
    """流式驱动 assign_facility;objective = Σ F[i][j]·D[σ(i)][σ(j)]。"""
    fn = ns["assign_facility"]
    rng = np.random.default_rng(int(instance.get("seed", 7)))
    n = int(instance.get("n", 12))
    F = rng.integers(0, 10, (n, n)).astype(float)
    F = (F + F.T) / 2
    np.fill_diagonal(F, 0.0)
    D = rng.integers(1, 20, (n, n)).astype(float)
    D = (D + D.T) / 2
    np.fill_diagonal(D, 0.0)
    assign = [-1] * n
    for f in range(n):
        avail = [x for x in range(n) if x not in assign]
        try:
            pos = int(fn(f, avail, F, D, list(assign)))
        except Exception:
            return 10**9
        if pos not in avail:
            return 10**9
        assign[f] = pos
    return float(sum(F[i, j] * D[assign[i], assign[j]]
                     for i in range(n) for j in range(n)))
'''

# ---------------------------------------------------------------- power_trading

_POWER_TRADING_JUDGE = '''
import numpy as np

def judge(instance, config, ns):
    """4 阶段流式驱动 propose_target_mwh(官方 ascend=False)。
    objective = 相对被动基线(每阶段买入 p50 预测)的净购电成本节省率,越大越好。
    结算规则(自洽定义):交易按当阶段 p50 价执行、|Δ| 收手续费;持仓先抵扣当期
    真实负荷,缺口按 1.5× 现货惩罚价补足;期末余量按末日价格回售。"""
    fn = ns["propose_target_mwh"]
    rng = np.random.default_rng(int(instance.get("seed", 7)))
    stages = int(instance.get("stages", 4))
    fee = float(instance.get("fee", 1.5))
    L = rng.uniform(80.0, 150.0, stages)
    P = rng.uniform(30.0, 70.0, stages)

    def run(policy):
        pos, cost = 0.0, 0.0
        for t in range(stages):
            later_l = L[t + 1] if t + 1 < stages else L[t]
            later_p = P[t + 1] if t + 1 < stages else P[t]
            target = policy(t, L[t], P[t], later_l, later_p, pos)
            target = max(0.0, min(float(target), L[t] * 1.15))
            delta = target - pos
            cost += max(0.0, delta) * P[t] + fee * abs(delta) - max(0.0, -delta) * P[t]
            pos = target
            if pos < L[t]:
                cost += (L[t] - pos) * P[t] * 1.5
                pos = 0.0
            else:
                pos -= L[t]
        cost -= pos * P[-1]
        return cost

    def passive(t, load_true, price_true, later_l, later_p, pos):
        bands = (load_true * 0.85, load_true, load_true * 1.15,
                 price_true * 0.9, price_true, price_true * 1.1)
        return bands[1]

    def heuristic(t, load_true, price_true, later_l, later_p, pos):
        l10, l50, l90 = load_true * 0.85, load_true, load_true * 1.15
        p10, p50, p90 = price_true * 0.9, price_true, price_true * 1.1
        return fn(t, l10, l50, l90, p10, p50, p90, later_l, later_p, pos, fee)

    base = run(passive)
    mine = run(heuristic)
    if base <= 0:
        return 0.0
    return float((base - mine) / base)
'''

# ---------------------------------------------------------------- 注册表

EXTENDED: dict[str, dict] = {
    "cvrp": {
        "name": "Capacitated Vehicle Routing (带容量车辆路径)",
        "ascend": True,
        "description": "从仓库出发逐客户决策(-1 回仓),容量约束下服务全部客户。objective=总行驶距离。",
        "evaluate": {
            "entry": "find_best_route",
            "entry_doc": ("def find_best_route(current_node, remaining_demands, "
                          "vehicle_capacity, current_load, distance_matrix, demand_list) -> int  # -1 回仓库"),
            "instance": {"seed": 7, "n": 21, "cap": 25},
            "prescreen_instance": {"seed": 7, "n": 12, "cap": 20},
            "judge": _CVRP_JUDGE, "judge_entry": "judge", "timeout": 10,
        },
    },
    "mtsp": {
        "name": "Multiple TSP (多旅行商)",
        "ascend": True,
        "description": "m 个销售员从仓库出发逐点决策(-1 换人),objective=总行驶距离。",
        "evaluate": {
            "entry": "select_next_node",
            "entry_doc": ("def select_next_node(current_node, unvisited_nodes, "
                          "distance_matrix, remaining_salesmen) -> int  # -1 换销售员"),
            "instance": {"seed": 7, "n": 32, "m": 4},
            "prescreen_instance": {"seed": 7, "n": 16, "m": 3},
            "judge": _MTSP_JUDGE, "judge_entry": "judge", "timeout": 10,
        },
    },
    "vrptw": {
        "name": "VRP with Time Windows (带时间窗车辆路径)",
        "ascend": True,
        "description": "时间窗+容量约束下逐客户决策(-1 回仓),objective=总行驶距离(窗/容量违约判罚)。",
        "evaluate": {
            "entry": "select_next_customer",
            "entry_doc": ("def select_next_customer(current_node, current_time, remaining_demands, "
                          "vehicle_capacity, current_load, distance_matrix, demand_list, "
                          "time_windows, service_times) -> int  # -1 回仓库"),
            "instance": {"seed": 7, "n": 16, "cap": 20},
            "prescreen_instance": {"seed": 7, "n": 12, "cap": 15},
            "judge": _VRPTW_JUDGE, "judge_entry": "judge", "timeout": 10,
        },
    },
    "orienteering": {
        "name": "Orienteering (定向越野)",
        "ascend": True,
        "description": "预算内逐点决定访问(-1 结束,需能返仓),objective=-已获利润(利润越大越好)。",
        "evaluate": {
            "entry": "select_next_node",
            "entry_doc": ("def select_next_node(current_node, visited, profits, "
                          "distance_matrix, budget_left, total_profit) -> int  # -1 结束"),
            "instance": {"seed": 7, "n": 25, "budget_mult": 5},
            "prescreen_instance": {"seed": 7, "n": 12, "budget_mult": 4},
            "judge": _ORIENTEERING_JUDGE, "judge_entry": "judge", "timeout": 10,
        },
    },
    "setcover": {
        "name": "Set Cover (集合覆盖)",
        "ascend": True,
        "description": "逐个选集覆盖全部元素(None 结束),objective=选用集总成本。",
        "evaluate": {
            "entry": "select_next_set",
            "entry_doc": ("def select_next_set(uncovered_elements, set_membership, "
                          "set_costs) -> int  # 集合下标;覆盖完成返回 None"),
            "instance": {"seed": 7, "n_elem": 60, "n_sets": 25},
            "prescreen_instance": {"seed": 7, "n_elem": 20, "n_sets": 10},
            "judge": _SETCOVER_JUDGE, "judge_entry": "judge", "timeout": 10,
        },
    },
    "vertexcover": {
        "name": "Vertex Cover (最小点覆盖)",
        "ascend": True,
        "description": "逐点选入覆盖集(None 结束),objective=覆盖集大小(有边残留判罚)。",
        "evaluate": {
            "entry": "select_next_vertex",
            "entry_doc": ("def select_next_vertex(uncovered_edges, adjacency_matrix, "
                          "current_cover) -> int  # 顶点下标;覆盖完成返回 None"),
            "instance": {"seed": 7, "n": 30},
            "prescreen_instance": {"seed": 7, "n": 16},
            "judge": _VERTEXCOVER_JUDGE, "judge_entry": "judge", "timeout": 10,
        },
    },
    "maxclique": {
        "name": "Maximum Clique (最大团)",
        "ascend": True,
        "description": "逐点扩张团(None 结束),objective=-团大小。",
        "evaluate": {
            "entry": "select_next_vertex",
            "entry_doc": ("def select_next_vertex(current_clique, candidate_vertices, "
                          "adjacency_matrix) -> int  # 候选顶点;扩张结束返回 None"),
            "instance": {"seed": 7, "n": 30},
            "prescreen_instance": {"seed": 7, "n": 16},
            "judge": _MAXCLIQUE_JUDGE, "judge_entry": "judge", "timeout": 10,
        },
    },
    "kcenter": {
        "name": "K-Center (k 中心)",
        "ascend": True,
        "description": "逐个选 k 个中心(None 提前停),objective=覆盖半径(最大最近中心距)。",
        "evaluate": {
            "entry": "select_next_center",
            "entry_doc": ("def select_next_center(selected_centers, candidate_nodes, "
                          "distance_matrix, k) -> int  # 中心下标;选满/提前停返回 None"),
            "instance": {"seed": 7, "n": 30, "k": 4},
            "prescreen_instance": {"seed": 7, "n": 15, "k": 3},
            "judge": _KCENTER_JUDGE, "judge_entry": "judge", "timeout": 10,
        },
    },
    "steinertree": {
        "name": "Steiner Tree (斯坦纳树)",
        "ascend": True,
        "description": "逐终端接入生成树(None 结束),objective=树总权(最短路度量累加)。",
        "evaluate": {
            "entry": "select_next_terminal",
            "entry_doc": ("def select_next_terminal(current_tree, unconnected_terminals, "
                          "adjacency_matrix, distances) -> int  # 终端下标;全部连通返回 None"),
            "instance": {"seed": 7, "n": 20, "n_terms": 4},
            "prescreen_instance": {"seed": 7, "n": 12, "n_terms": 3},
            "judge": _STEINERTREE_JUDGE, "judge_entry": "judge", "timeout": 10,
        },
    },
    "partition": {
        "name": "Partition (数组分拆)",
        "ascend": True,
        "description": "逐数决策分入 A/B 组,objective=|组A - 组B|。",
        "evaluate": {
            "entry": "assign_number",
            "entry_doc": "def assign_number(number_id, sum_a, sum_b, numbers) -> 0|1",
            "instance": {"seed": 7, "n": 30},
            "prescreen_instance": {"seed": 7, "n": 14},
            "judge": _PARTITION_JUDGE, "judge_entry": "judge", "timeout": 10,
        },
    },
    "pfsp": {
        "name": "Permutation Flow-shop (排列流水车间)",
        "ascend": True,
        "description": "逐位置选作业,objective=makespan(逐机器链式递推)。",
        "evaluate": {
            "entry": "select_next_job",
            "entry_doc": ("def select_next_job(unscheduled_jobs, current_schedule, "
                          "processing_times, num_machines) -> int  # 作业下标"),
            "instance": {"seed": 7, "n": 10, "m": 3},
            "prescreen_instance": {"seed": 7, "n": 6, "m": 3},
            "judge": _PFSP_JUDGE, "judge_entry": "judge", "timeout": 10,
        },
    },
    "jsp": {
        "name": "Job-shop Scheduling (作业车间调度)",
        "ascend": True,
        "description": "非延迟调度逐步选作业(其下一道工序随即排产),objective=makespan。",
        "evaluate": {
            "entry": "select_next_job",
            "entry_doc": ("def select_next_job(available_operations, job_progress, "
                          "operation_times, machine_ready_times, machine_of_op) -> int  # 作业下标"),
            "instance": {"seed": 7, "n": 5, "ops": 3, "m": 3},
            "prescreen_instance": {"seed": 7, "n": 4, "ops": 3, "m": 3},
            "judge": _JSP_JUDGE, "judge_entry": "judge", "timeout": 10,
        },
    },
    "smtwt": {
        "name": "Single Machine Total Weighted Tardiness (单机加权拖期)",
        "ascend": True,
        "description": "逐位置排产,objective=总加权拖期 Σ w·max(0, C-d)。",
        "evaluate": {
            "entry": "select_next_job",
            "entry_doc": ("def select_next_job(unscheduled_jobs, current_time, "
                          "processing_times, due_dates, weights) -> int  # 作业下标"),
            "instance": {"seed": 7, "n": 15},
            "prescreen_instance": {"seed": 7, "n": 8},
            "judge": _SMTWT_JUDGE, "judge_entry": "judge", "timeout": 10,
        },
    },
    "parmachine": {
        "name": "Parallel Machine Scheduling (平行机调度)",
        "ascend": True,
        "description": "逐作业指派机器(越界索引判罚),objective=makespan(负载峰值)。",
        "evaluate": {
            "entry": "assign_job",
            "entry_doc": "def assign_job(job_id, machine_loads, processing_times, num_machines) -> int  # 机器下标",
            "instance": {"seed": 7, "n": 25, "m": 4},
            "prescreen_instance": {"seed": 7, "n": 12, "m": 3},
            "judge": _PARMACHINE_JUDGE, "judge_entry": "judge", "timeout": 10,
        },
    },
    "qap": {
        "name": "Quadratic Assignment (二次分配)",
        "ascend": True,
        "description": "逐设施指派位置,objective=Σ F·D(流量×距离二次代价)。",
        "evaluate": {
            "entry": "assign_facility",
            "entry_doc": ("def assign_facility(facility_id, available_positions, "
                          "flow_matrix, distance_matrix, current_assignment) -> int  # 位置下标"),
            "instance": {"seed": 7, "n": 12},
            "prescreen_instance": {"seed": 7, "n": 8},
            "judge": _QAP_JUDGE, "judge_entry": "judge", "timeout": 10,
        },
    },
    "power_trading": {
        "name": "Power Trading (电力交易策略)",
        "ascend": False,
        "description": ("年度/月度/月内/日前 4 阶段逐级决定目标持仓;objective=相对被动基线的"
                        "净购电成本节省率(官方 ascend=False,越大越好)。"),
        "evaluate": {
            "entry": "propose_target_mwh",
            "entry_doc": ("def propose_target_mwh(stage_index, load_p10, load_p50, load_p90, "
                          "price_p10, price_p50, price_p90, later_load_p50, later_price_p50, "
                          "position_before_mwh, transaction_fee) -> float  # 标量,截断到 [0, load_p90]"),
            "instance": {"seed": 7, "stages": 4, "fee": 1.5},
            "prescreen_instance": {"seed": 7, "stages": 4, "fee": 1.5},
            "judge": _POWER_TRADING_JUDGE, "judge_entry": "judge", "timeout": 10,
        },
    },
}
