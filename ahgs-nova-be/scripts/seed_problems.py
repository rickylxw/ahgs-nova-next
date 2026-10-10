# -*- coding: utf-8 -*-
"""注册内建裁判契约题目(仅题目与判定程序,不含任何解题种子)。

用法(在 ahgs-nova-be 目录):
    python scripts/seed_problems.py
任意 Python 可跑(自动落到仓库 .venv,同 serve.py)。

种子从哪里来:平台原生支持种子库(POST /api/v2/seeds)与运行时 seed_code/seed_id
注入,由使用者自行决定是否上传;本脚本刻意不携带任何启发式实现。
"""
import asyncio
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def _ensure_deps() -> None:
    try:
        import fastapi  # noqa: F401
        return
    except ModuleNotFoundError:
        pass
    for candidate in (REPO_ROOT / ".venv" / "Scripts" / "python.exe",
                      REPO_ROOT / ".venv" / "bin" / "python",
                      REPO_ROOT / ".venv" / "Scripts" / "python"):
        if candidate.exists():
            proc = subprocess.run([str(candidate), str(Path(__file__).resolve()),
                                   *sys.argv[1:]])
            raise SystemExit(proc.returncode)
    raise SystemExit("fastapi 未安装且未找到仓库 .venv,请先 pip install -e .")


_ensure_deps()

from app.contracts.builtin import CONTRACTS  # noqa: E402
from app.context import AppContext  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.core.security import now_utc  # noqa: E402
from app.db.session import init_db  # noqa: E402
from app.db.models import Problem  # noqa: E402


async def main() -> None:
    ctx = AppContext.build(Settings())
    await init_db(ctx.engine)
    async with ctx.session_factory() as db:
        for key, spec in CONTRACTS.items():
            problem = await db.get(Problem, key)
            if problem is None:
                problem = Problem(key=key, created_at=now_utc())
                db.add(problem)
            problem.name = spec["name"]
            problem.kind = "optimization"
            problem.ascend = spec["ascend"]
            problem.contract = {"description": spec["description"],
                                "evaluate": spec["evaluate"]}
            print(f"题目已注册: {key}(ascend={spec['ascend']}, 裁判就绪;不含任何种子)")
        await db.commit()
    await ctx.engine.dispose()
    print("完成。开跑:POST /api/v2/run {problem_key, config:{seed_code 或 seed_id, llm_model, ...}}")


if __name__ == "__main__":
    asyncio.run(main())
