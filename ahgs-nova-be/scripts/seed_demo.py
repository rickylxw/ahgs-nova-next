# -*- coding: utf-8 -*-
"""种子数据:管理员 + 21 题 + 两只井字棋示例 bot + demo 用户。

用法(在 ahgs-nova-be 目录,数据库配置走环境变量/.env):
    python scripts/seed_demo.py
"""
import asyncio
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def _ensure_deps() -> None:
    """仓库 venv 里已装 fastapi;若当前解释器没有,自动切到 .venv 重跑。"""
    try:
        import fastapi  # noqa: F401
        return
    except ModuleNotFoundError:
        pass
    # 不用 os.execv:Windows 下它按空格切分 argv,仓库路径含空格时断裂
    for candidate in (REPO_ROOT / ".venv" / "Scripts" / "python.exe",
                      REPO_ROOT / ".venv" / "bin" / "python",
                      REPO_ROOT / ".venv" / "Scripts" / "python"):
        if candidate.exists():
            proc = subprocess.run([str(candidate), str(Path(__file__).resolve()),
                                   *sys.argv[1:]])
            raise SystemExit(proc.returncode)
    raise SystemExit(
        "fastapi 未安装且未找到仓库 .venv。请先执行:\n"
        "  python -m venv .venv\n"
        "  .venv/Scripts/python -m pip install -e .\n"
        "然后重跑本脚本。")


_ensure_deps()

from app.context import AppContext  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.core.security import hash_password, now_utc  # noqa: E402
from app.db.session import init_db  # noqa: E402
from app.db.models import Bot, Problem, User  # noqa: E402

# 20 题契约的最小骨架(ascend 语义来自官方:True=越小越好)
PROBLEMS = [
    ("tsp", "旅行商问题(TSP)", True),
    ("knapsack", "背包问题(Knapsack)", True),
    ("maxcut", "最大割(MaxCut)", False),
    ("binpacking", "装箱问题(Bin Packing)", True),
    ("graphcoloring", "图着色(Graph Coloring)", True),
    ("cvrp", "车辆路径(CVRP)", True),
    ("jsp", "作业车间调度(JSP)", True),
    ("kcenter", "K 中心(K-Center)", True),
    ("mtsp", "多旅行商问题(mTSP)", True),
    ("orienteering", "定向越野(Orienteering)", True),
    ("parmachine", "并行机调度(Parallel Machine)", True),
    ("partition", "平衡划分(Partition)", True),
    ("pfsp", "流水车间调度(PFSP)", True),
    ("power_trading", "电力交易(Power Trading)", False),
    ("qap", "二次分配问题(QAP)", True),
    ("setcover", "集合覆盖(Set Cover)", True),
    ("smtwt", "单机加权延误(SMTWT)", True),
    ("steinertree", "斯坦纳树(Steiner Tree)", True),
    ("vertexcover", "最小顶点覆盖(Vertex Cover)", True),
    ("vrptw", "带时间窗车辆路径(VRPTW)", True),
]

# 每题默认进化参数(demo 值;写入 contract.evolve_defaults,管理端可随时改)
PROBLEM_EVOLVE_DEFAULTS = {
    "tsp": {"population_size": 10, "num_generations": 15},
    "mtsp": {"population_size": 10, "num_generations": 15},
    "cvrp": {"population_size": 10, "num_generations": 15},
    "vrptw": {"population_size": 10, "num_generations": 15},
    "orienteering": {"population_size": 10, "num_generations": 12},
    "jsp": {"population_size": 8, "num_generations": 12},
    "pfsp": {"population_size": 8, "num_generations": 12},
    "smtwt": {"population_size": 8, "num_generations": 12},
    "parmachine": {"population_size": 8, "num_generations": 12},
    "kcenter": {"population_size": 12, "num_generations": 15},
    "qap": {"population_size": 12, "num_generations": 15},
    "power_trading": {"population_size": 6, "num_generations": 8},
}

CENTER_BOT = """def move(board, me):
    if board[4] == 0:
        return 4
    for i, v in enumerate(board):
        if v == 0:
            return i
    return -1
"""

RANDOMISH_BOT = """import random
rng = random.Random(2026)

def move(board, me):
    empty = [i for i, v in enumerate(board) if v == 0]
    return rng.choice(empty) if empty else -1
"""


async def main() -> None:
    settings = Settings()
    ctx = AppContext.build(settings)
    await init_db(ctx.engine)

    async with ctx.session_factory() as db:
        admin_name = settings.admin_username or "admin"
        admin_pwd = settings.admin_password or "nova-admin-2026"
        from sqlalchemy import select

        admin = (await db.scalars(
            select(User).where(User.username == admin_name))).first()
        if admin is None:
            admin = User(username=admin_name, role="admin",
                         display_name=settings.admin_display_name,
                         password_hash=hash_password(admin_pwd),
                         created_at=now_utc())
            db.add(admin)
            print(f"管理员已创建: {admin_name} / {admin_pwd}(请立即修改)")
        for key, name, ascend in PROBLEMS:
            seed_contract = ({"evolve_defaults": PROBLEM_EVOLVE_DEFAULTS[key]}
                             if key in PROBLEM_EVOLVE_DEFAULTS else {})
            row = await db.get(Problem, key)
            if row is None:
                db.add(Problem(key=key, name=name, kind="optimization", ascend=ascend,
                               contract=seed_contract, created_at=now_utc()))
            else:
                if row.name == key:
                    # 旧版种子把英文名写成了 key;仅在未被用户改名时升级为中文名
                    row.name = name
                if not (row.contract or {}) and seed_contract:
                    # 旧种子没有每题默认参数;契约仍为空时补写(不覆盖用户已配置的契约)
                    row.contract = seed_contract
        print(f"题目已注册: {len(PROBLEMS)} 题(optimization)")
        if not (await db.scalars(select(Bot))).first():
            db.add(Bot(user_id=admin.id, arena_key="tictactoe", name="CenterBot",
                       code=CENTER_BOT, rating=1000.0, created_at=now_utc(),
                       updated_at=now_utc()))
            db.add(Bot(user_id=admin.id, arena_key="tictactoe", name="RandomBot",
                       code=RANDOMISH_BOT, rating=1000.0, created_at=now_utc(),
                       updated_at=now_utc()))
            print("示例 bot 已创建: CenterBot / RandomBot(tictactoe)")
        demo = (await db.scalars(
            select(User).where(User.username == "demo"))).first()
        if demo is None:
            db.add(User(username="demo", role="user", display_name="Demo User",
                        password_hash=hash_password("demo-password-123"),
                        created_at=now_utc()))
            print("演示用户已创建: demo / demo-password-123")
        await db.commit()
    await ctx.engine.dispose()
    print("完成。")


if __name__ == "__main__":
    asyncio.run(main())
