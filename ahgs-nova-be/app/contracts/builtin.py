# -*- coding: utf-8 -*-
"""内建题目契约:判定程序按官方平台语义实现,配合本地进化引擎(evolve_llm)。

与官方的一致性分两层:
- **接口与合法性(完全对齐)**:流式调用序列、参数形态(numpy 数组)、逐步违约
  判定(-1/越界/超装/相邻同色 → 10**9 罚值)均移植自 `_prescreen_specs.py` 的
  `_mini_drive` —— 该套驱动在官方平台上验证过(预筛存活率),即官方评估器的
  逆向等价物;各题接口与 `_prob_*.json` 的 fun_args/fun_return 逐一核对。
- **目标值公式(按官方描述重建)**:官方 ascend=True 而描述是"最大价值/最多割/
  最少箱/最少色",说明服务端把目标转成了极小化量;精确公式与聚合方式在服务端
  train pkl 里,未公开。本契约按描述取自然极小化变换(见各 judge docstring),
  knapsack 已有平台锚点验证(真实种子得 0.0 = 冲榜记录"0.0 并列最优")。
  若拿到官方 evaluator 源码,把 judge 字段整体替换即可,协议不变。

数据由 instance 里的 seed/n 确定性生成(同 config 可复现,种群间公平)。
本模块刻意不包含任何启发式实现/种子 —— 解法属于使用者,经种子库自行上传。
"""

PENALTY = 10 ** 9

# ---------------------------------------------------------------- knapsack

_KNAPSACK_JUDGE = '''
import numpy as np

def judge(instance, config, ns):
    """流式驱动 select_item;objective = 剩余容量(0 = 完美装满)。"""
    fn = ns["select_item"]
    rng = np.random.default_rng(int(instance.get("seed", 7)))
    n = int(instance.get("n", 40))
    w = rng.integers(1, 50, n).astype(float)
    v = w + rng.integers(0, 20, n)
    C = float(int(0.2 * w.sum()))
    rem = C
    for i in range(n):
        try:
            t = int(fn(i, rem, w, v, n))
        except Exception:
            return 10**9
        if t not in (0, 1):
            return 10**9
        if t == 1:
            if w[i] > rem + 1e-9:
                return 10**9
            rem -= w[i]
    return float(rem)
'''

# ---------------------------------------------------------------- maxcut

_MAXCUT_JUDGE = '''
import numpy as np

def judge(instance, config, ns):
    """流式驱动 assign_node;objective = 总权重 - 割边权重(未切部分)。"""
    fn = ns["assign_node"]
    rng = np.random.default_rng(int(instance.get("seed", 7)))
    n = int(instance.get("n", 80))
    p = float(instance.get("p", 0.25))
    wmax = int(instance.get("wmax", 8))
    A = np.zeros((n, n))
    mask = np.triu(rng.random((n, n)) < p, 1)
    A[mask] = rng.integers(1, wmax + 1, int(mask.sum()))
    A = A + A.T
    part = -np.ones(n, dtype=int)
    for node in range(n):
        try:
            s = int(fn(node, np.arange(node, n), A, part))
        except Exception:
            return 10**9
        if s not in (0, 1):
            return 10**9
        part[node] = s
    ii, jj = np.triu_indices(n, 1)
    cut = A[ii, jj][part[ii] != part[jj]].sum()
    return float(A.sum() / 2 - cut)
'''

# ---------------------------------------------------------------- binpacking

_BINPACKING_JUDGE = '''
import numpy as np

def judge(instance, config, ns):
    """流式驱动 place_item(-1=开新箱);objective = 用箱数/理论下界。"""
    fn = ns["place_item"]
    rng = np.random.default_rng(int(instance.get("seed", 7)))
    n = int(instance.get("n", 40))
    sizes = np.sort(rng.uniform(0.05, 0.4, n))[::-1]
    rems: list[float] = []
    for i in range(n):
        try:
            k = int(fn(float(sizes[i]), np.array(rems), sizes, n))
        except Exception:
            return 10**9
        if k == -1:
            rems.append(1.0 - sizes[i])
        elif 0 <= k < len(rems) and rems[k] >= sizes[i] - 1e-9:
            rems[k] -= sizes[i]
        else:
            return 10**9
    lb = max(1, int(np.ceil(sizes.sum() - 1e-9)))
    return len(rems) / lb
'''

# ---------------------------------------------------------------- graphcoloring

_GRAPHCOLORING_JUDGE = '''
import numpy as np

def judge(instance, config, ns):
    """流式驱动 choose_color(c==k 开新色);objective = 颜色数(末检相邻同色)。"""
    fn = ns["choose_color"]
    rng = np.random.default_rng(int(instance.get("seed", 7)))
    n = int(instance.get("n", 60))
    p = float(instance.get("p", 0.2))
    A = np.zeros((n, n))
    mask = np.triu(rng.random((n, n)) < p, 1)
    A[mask] = 1
    A = A + A.T
    cols = -np.ones(n, dtype=int)
    k = 0
    for node in range(n):
        try:
            c = int(fn(node, A, cols, k))
        except Exception:
            return 10**9
        if not (0 <= c <= k):
            return 10**9
        if c == k:
            k += 1
        cols[node] = c
    ii, jj = np.triu_indices(n, 1)
    if (cols[ii] == cols[jj])[A[ii, jj] > 0].any():
        return 10**9
    return float(k)
'''

# ---------------------------------------------------------------- tsp

_TSP_JUDGE = '''
import numpy as np

def judge(instance, config, ns):
    """流式驱动 select_next_node(评估器闭合回路);objective = 回路长/最近邻基线。"""
    fn = ns["select_next_node"]
    rng = np.random.default_rng(int(instance.get("seed", 7)))
    n = int(instance.get("n", 50))
    # 官方描述:给定节点坐标 → 坐标均匀采样,距离取欧氏(整数化,同官方风格)
    span = float(instance.get("span", 100.0))
    pts = rng.uniform(0.0, span, (n, 2))
    diff = pts[:, None, :] - pts[None, :, :]
    D = np.sqrt((diff ** 2).sum(-1))
    np.fill_diagonal(D, 0.0)
    un = set(range(1, n))
    cur, dist = 0, 0.0
    while un:
        try:
            nxt = int(fn(cur, 0, np.array(sorted(un)), D))
        except Exception:
            return 10**9
        if nxt not in un:
            return 10**9
        dist += D[cur, nxt]
        un.discard(nxt)
        cur = nxt
    dist += D[cur, 0]
    # 最近邻基线(确定性 tie-break)
    base_un, base_cur, base_dist = set(range(1, n)), 0, 0.0
    while base_un:
        nxt = min(base_un, key=lambda x: (D[base_cur, x], x))
        base_dist += D[base_cur, nxt]
        base_un.discard(nxt)
        base_cur = nxt
    base_dist += D[base_cur, 0]
    return float(dist / base_dist)
'''

# ---------------------------------------------------------------- 契约注册表

CONTRACTS: dict[str, dict] = {
    "knapsack": {
        "name": "0/1 Knapsack (背包问题)",
        "ascend": True,
        "description": ("0/1背包问题:逐个物品决策拿(1)或不拿(0)。objective=剩余容量,"
                        "0 为并列最优(平台锚点)。"),
        "evaluate": {
            "entry": "select_item",
            "entry_doc": ("def select_item(current_index, remaining_capacity, "
                          "weights, values, num_items) -> 0|1  # 全部数据为 numpy 数组"),
            "instance": {"seed": 7, "n": 40},
            "prescreen_instance": {"seed": 7, "n": 12},
            "judge": _KNAPSACK_JUDGE,
            "judge_entry": "judge",
            "timeout": 10,
        },
    },
    "maxcut": {
        "name": "Maximum Cut (最大割)",
        "ascend": True,
        "description": ("带权无向图逐点分配到 0/1 两侧。objective=未切权重(总权重-割边权重),"
                        "越小切得越多。"),
        "evaluate": {
            "entry": "assign_node",
            "entry_doc": ("def assign_node(node_id, unassigned_nodes, "
                          "adjacency_matrix, current_partition) -> 0|1  # 未分配侧记 -1"),
            "instance": {"seed": 7, "n": 80, "p": 0.25, "wmax": 8},
            "prescreen_instance": {"seed": 7, "n": 20, "p": 0.25, "wmax": 8},
            "judge": _MAXCUT_JUDGE,
            "judge_entry": "judge",
            "timeout": 10,
        },
    },
    "binpacking": {
        "name": "Bin Packing (装箱问题)",
        "ascend": True,
        "description": ("容量 1.0 的箱子逐件装入,返回箱下标或 -1 开新箱。"
                        "objective=用箱数/理论下界,1.0 为完美。"),
        "evaluate": {
            "entry": "place_item",
            "entry_doc": ("def place_item(item_size, remaining_capacities, "
                          "item_sizes, num_items) -> int  # -1 开新箱"),
            "instance": {"seed": 7, "n": 40},
            "prescreen_instance": {"seed": 7, "n": 12},
            "judge": _BINPACKING_JUDGE,
            "judge_entry": "judge",
            "timeout": 10,
        },
    },
    "graphcoloring": {
        "name": "Graph Coloring (图着色)",
        "ascend": True,
        "description": ("逐点着色,返回 0..k(c==k 开新色)。objective=颜色数,"
                        "最终相邻同色判罚值。"),
        "evaluate": {
            "entry": "choose_color",
            "entry_doc": ("def choose_color(node_id, adjacency_matrix, "
                          "current_colors, num_colors_used) -> int  # c==k 开新色"),
            "instance": {"seed": 7, "n": 60, "p": 0.2},
            "prescreen_instance": {"seed": 7, "n": 15, "p": 0.2},
            "judge": _GRAPHCOLORING_JUDGE,
            "judge_entry": "judge",
            "timeout": 10,
        },
    },
    "tsp": {
        "name": "Traveling Salesman Problem (旅行商)",
        "ascend": True,
        "description": ("从节点 0 出发逐点选择下一节点,评估器闭合回路。"
                        "objective=回路长度/最近邻基线。"),
        "evaluate": {
            "entry": "select_next_node",
            "entry_doc": ("def select_next_node(current_node, destination_node, "
                          "unvisited_nodes, distance_matrix) -> int  # 回路由评估器闭合"),
            "instance": {"seed": 7, "n": 50, "span": 100.0},
            "prescreen_instance": {"seed": 7, "n": 12, "span": 100.0},
            "judge": _TSP_JUDGE,
            "judge_entry": "judge",
            "timeout": 10,
        },
    },
}

# 扩展 16 题并入统一注册表(builtin 五题优先,extended 覆盖同名键)
from .extended import EXTENDED  # noqa: E402

CONTRACTS.update(EXTENDED)
