# -*- coding: utf-8 -*-
"""从官方快照同步每题契约数据(problem contract)。

默认**离线**工作:读取本地快照 scripts/upstream_problems.json,把 description /
函数签名 / train_data 等字段与 evolve_defaults 数值参数合并进本地题目契约,
全程不向官方平台发请求。官方数据有更新时,显式执行 --fetch 拉一次并刷新快照。

- 只更新本地已存在的题目;快照多出的题仅提示,不自动创建;
- 契约中已有的非空键(如 evaluate / evolve_defaults 已配置项)不覆盖,
  description 以快照(官方)为准强制覆盖,evolve_defaults 数值键以快照为准。

用法(在 ahgs-nova-be 目录):
    python scripts/sync_problem_contracts.py                # 离线:按快照同步
    python scripts/sync_problem_contracts.py --dry-run      # 只预览
    python scripts/sync_problem_contracts.py --fetch        # 访问官方一次,刷新快照并同步
"""
import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

DEFAULT_UPSTREAM = os.environ.get("NOVA_UPSTREAM_BASE", "http://10.201.186.15:8090")
SNAPSHOT_PATH = Path(__file__).resolve().parent / "upstream_problems.json"

# 上游 default_config 中属于进化参数的数值键(其余如 llm_model 不属于"每题参数")
EVOLVE_NUMERIC_KEYS = (
    "population_size", "num_generations", "num_mutation",
    "num_hybridization", "num_reflection", "num_policy_updates",
)

# 官方平台全局默认(老前端 EVO_DEFAULTS):上游没有每题值的参数,用这套补齐,
# 使每题的 evolve_defaults 六键齐全(官方平台对所有题也是套用这组全局值)。
OFFICIAL_GLOBAL_DEFAULTS = {
    "population_size": 8, "num_generations": 10, "num_mutation": 3,
    "num_hybridization": 3, "num_reflection": 3, "num_policy_updates": 1,
}

# 从上游详情复制进契约的字段(非空才写)
COPY_FIELDS = (
    "description", "fun_name", "fun_args", "fun_return", "fun_notes",
    "problem_path", "train_data", "train_solution", "category",
)

# 以官方为准强制覆盖的字段(本地改动会被官方值取代;其余字段仍只在本地为空时填充)
FORCE_OVERWRITE_FIELDS = ("description",)


def _ensure_deps() -> None:
    try:
        import fastapi  # noqa: F401
        import httpx  # noqa: F401
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
    raise SystemExit("fastapi/httpx 未安装且未找到仓库 .venv。")


_ensure_deps()

import httpx  # noqa: E402

from app.context import AppContext  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.db.models import Problem  # noqa: E402
from app.db.session import init_db  # noqa: E402


async def fetch_upstream(base: str) -> dict[str, dict]:
    """拉上游全部题目详情,key → detail dict。"""
    base = base.rstrip("/")
    async with httpx.AsyncClient(timeout=15, trust_env=False) as cli:
        r = await cli.get(f"{base}/api/problems")
        r.raise_for_status()
        keys = [p["key"] for p in r.json().get("problems", [])]
        out = {}
        for k in keys:
            rd = await cli.get(f"{base}/api/problems/{k}")
            if rd.status_code == 200:
                out[k] = rd.json()
        return out


def merge_contract(local_contract: dict, up: dict) -> tuple[dict, list[str]]:
    """返回 (新契约, 变更键列表)。已有非空键不覆盖;evolve_defaults 数值键以上游为准。"""
    c = dict(local_contract or {})
    changed: list[str] = []
    for f in COPY_FIELDS:
        v = up.get(f)
        if v in (None, "", []) or (isinstance(v, str) and not v.strip()):
            continue
        if f in FORCE_OVERWRITE_FIELDS:
            if c.get(f) != v:
                c[f] = v
                changed.append(f)
        elif not c.get(f):
            c[f] = v
            changed.append(f)
    dc = up.get("default_config") or {}
    # 叠加顺序:官方全局默认 → 本地已配置(用户值保留) → 上游每题值(权威)
    ed = dict(OFFICIAL_GLOBAL_DEFAULTS)
    ed.update(c.get("evolve_defaults") or {})
    for k in EVOLVE_NUMERIC_KEYS:
        v = dc.get(k)
        if isinstance(v, (int, float)):
            ed[k] = v
    orig_ed = c.get("evolve_defaults") or {}
    for k in EVOLVE_NUMERIC_KEYS:
        if k not in orig_ed:
            changed.append(f"evolve_defaults.{k}")
        elif orig_ed[k] != ed.get(k):
            changed.append(f"evolve_defaults.{k}")
    c["evolve_defaults"] = ed
    return c, changed


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true",
                    help="显式访问官方平台拉取最新数据并更新本地快照(默认不发起任何网络请求)")
    ap.add_argument("--upstream", default=DEFAULT_UPSTREAM,
                    help="仅在 --fetch 时使用的官方平台地址")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.fetch:
        print(f"从官方拉取: {args.upstream} …")
        upstream = await fetch_upstream(args.upstream)
        SNAPSHOT_PATH.write_text(json.dumps(upstream, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
        print(f"快照已更新: {SNAPSHOT_PATH}({len(upstream)} 题)")
    else:
        if not SNAPSHOT_PATH.exists():
            raise SystemExit(f"本地快照不存在({SNAPSHOT_PATH})。"
                             "首次使用请执行: python scripts/sync_problem_contracts.py --fetch")
        upstream = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        print(f"离线模式: 使用本地快照 {SNAPSHOT_PATH.name}({len(upstream)} 题),不访问官方。")

    settings = Settings()
    ctx = AppContext.build(settings)
    await init_db(ctx.engine)
    from sqlalchemy import select

    updated = 0
    async with ctx.session_factory() as db:
        rows = (await db.scalars(select(Problem))).all()
        for row in rows:
            up = upstream.get(row.key)
            if up is None:
                print(f"  - {row.key}: 快照无此题,跳过")
                continue
            new_contract, changed = merge_contract(row.contract, up)
            if not changed:
                print(f"  - {row.key}: 无变化")
                continue
            print(f"  ✓ {row.key}: 更新 {', '.join(changed)}")
            if not args.dry_run:
                row.contract = new_contract
            updated += 1
        local_keys = {r.key for r in rows}
        extra = sorted(set(upstream) - local_keys)
        if extra:
            print(f"快照多出本地没有的题(未创建): {', '.join(extra)}")
        if not args.dry_run and updated:
            await db.commit()
    await ctx.engine.dispose()
    print(f"{'[dry-run] ' if args.dry_run else ''}完成: {updated} 题有更新。")


if __name__ == "__main__":
    os.environ.setdefault("NOVA_MODE", "standalone")
    asyncio.run(main())
