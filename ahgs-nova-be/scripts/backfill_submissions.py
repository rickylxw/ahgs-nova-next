# -*- coding: utf-8 -*-
"""补录历史完成的 evolve 运行的提交(自动提交功能上线前完成的运行)。

用法(在 ahgs-nova-be 目录):
    python scripts/backfill_submissions.py
规则与运行期自动提交完全一致:NOVA_AUTO_SUBMIT 开启 + evolve kind +
best_objective 数值且非罚值 + 同 run 无既有提交;动作写审计日志。
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

from sqlalchemy import select  # noqa: E402

from app.context import AppContext  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.db.models import Run  # noqa: E402
from app.db.session import init_db  # noqa: E402
from app.services.orchestrator import AUTO_SUBMIT_KINDS, auto_submit_run  # noqa: E402


async def main() -> None:
    settings = Settings()
    if not settings.auto_submit:
        print("NOVA_AUTO_SUBMIT 未开启,补录无意义;.env 打开后再运行。")
        return
    ctx = AppContext.build(settings)
    await init_db(ctx.engine)
    created = skipped = 0
    async with ctx.session_factory() as db:
        runs = (await db.scalars(
            select(Run).where(Run.status == "completed")
        )).all()
        for run in runs:
            if run.kind not in AUTO_SUBMIT_KINDS:
                continue
            sub_id = await auto_submit_run(db, settings, run)
            if sub_id is None:
                skipped += 1
                continue
            created += 1
            print(f"补录: run {run.id} → submission {sub_id} "
                  f"({run.problem_key} = {run.best_objective})")
        await db.commit()
    await ctx.engine.dispose()
    print(f"完成:新建 {created} 条提交,跳过 {skipped} 个运行(罚值/重复/无最优)。")


if __name__ == "__main__":
    asyncio.run(main())
