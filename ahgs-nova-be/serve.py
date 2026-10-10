# -*- coding: utf-8 -*-
"""Nova Backend 启动器:任意 Python 均可运行(自动落到仓库 .venv)。

    python serve.py                 # http://127.0.0.1:8000
    python serve.py --port 8001
    python serve.py --reload        # 开发热重载
    python serve.py --host 0.0.0.0  # 局域网可达
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent


def _ensure_deps() -> None:
    """当前解释器缺 uvicorn 时,自动切到仓库 .venv 重跑(路径含空格也安全)。"""
    try:
        import uvicorn  # noqa: F401
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
    raise SystemExit(
        "uvicorn 未安装且未找到仓库 .venv。请先执行:\n"
        "  python -m venv .venv\n"
        "  .venv/Scripts/python -m pip install -e .\n"
        "然后重跑: python serve.py")


_ensure_deps()
os.chdir(REPO_ROOT)  # .env / data/ 相对路径与启动位置无关

import uvicorn  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="Nova Backend 启动器")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--reload", action="store_true", help="开发热重载")
    ap.add_argument("--workers", type=int, default=1)
    args = ap.parse_args()
    uvicorn.run("app.main:app", host=args.host, port=args.port,
                reload=args.reload, workers=args.workers)


if __name__ == "__main__":
    main()
