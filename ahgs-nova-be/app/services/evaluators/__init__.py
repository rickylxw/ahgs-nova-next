# -*- coding: utf-8 -*-
"""候选评估器:子进程隔离 + 结构化失败原因(计划 §4.3 预筛语义的产品化锚点)。

通用契约:候选代码实现 ``entry(instance, config) -> number | {"objective": number}``;
AHGS 各题的流式接口适配器(如"选下一个节点")在 standalone 阶段按题接入。
预筛 = 用合成迷你实例跑本评估器,崩溃/非法/超时候选在进主评估前淘汰。
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class EvalOutcome:
    ok: bool
    objective: float | None = None
    fail_reason: str | None = None   # load_error|crash|timeout|bad_return
    detail: str = ""
    elapsed_ms: int = 0

    def as_dict(self) -> dict:
        return {"ok": self.ok, "objective": self.objective,
                "fail_reason": self.fail_reason, "detail": self.detail,
                "elapsed_ms": self.elapsed_ms}


_WORKER_SRC = '''# -*- coding: utf-8 -*-
"""评估工作进程:加载候选源码,单次问答后退出。"""
import json, sys

def main():
    code_file, entry = sys.argv[1], sys.argv[2]
    req = json.loads(sys.stdin.readline())
    ns = {"__name__": "candidate"}
    try:
        with open(code_file, "r", encoding="utf-8") as f:
            exec(compile(f.read(), code_file, "exec"), ns)
    except Exception as e:
        sys.stdout.write(json.dumps({"error": f"load_error: {e!r}"}) + chr(10))
        return 2
    try:
        out = ns[entry](req.get("instance") or {}, req.get("config") or {})
    except Exception as e:
        sys.stdout.write(json.dumps({"error": f"crash: {e!r}"}) + chr(10))
        return 3
    obj = out.get("objective") if isinstance(out, dict) else out
    sys.stdout.write(json.dumps({"objective": obj}) + chr(10))
    return 0

if __name__ == "__main__":
    sys.exit(main())
'''


async def evaluate_candidate(code: str, *, entry: str = "evaluate",
                             instance: dict | None = None,
                             config: dict | None = None,
                             timeout: float = 10.0) -> EvalOutcome:
    start = time.monotonic()

    def elapsed() -> int:
        return int((time.monotonic() - start) * 1000)

    with tempfile.TemporaryDirectory(prefix="nova-eval-") as tmp:
        code_file = str(Path(tmp) / "candidate.py")
        worker_file = str(Path(tmp) / "worker.py")
        Path(code_file).write_text(code, encoding="utf-8")
        Path(worker_file).write_text(_WORKER_SRC, encoding="utf-8")
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, worker_file, code_file, entry,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except OSError as e:
            return EvalOutcome(False, fail_reason="crash", detail=str(e),
                               elapsed_ms=elapsed())
        try:
            payload = json.dumps({"instance": instance or {},
                                  "config": config or {}}).encode()
            out, _ = await asyncio.wait_for(proc.communicate(payload), timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return EvalOutcome(False, fail_reason="timeout",
                               detail=f"超过 {timeout}s", elapsed_ms=elapsed())
        except Exception as e:  # noqa: BLE001
            proc.kill()
            return EvalOutcome(False, fail_reason="crash", detail=str(e),
                               elapsed_ms=elapsed())

    if not out:
        return EvalOutcome(False, fail_reason="crash", detail="无输出",
                           elapsed_ms=elapsed())
    try:
        data = json.loads(out.decode("utf-8", "replace"))
    except ValueError:
        return EvalOutcome(False, fail_reason="bad_return",
                           detail=out[:200].decode("utf-8", "replace"),
                           elapsed_ms=elapsed())
    if "error" in data:
        reason = str(data["error"]).split(":", 1)[0]
        return EvalOutcome(False, fail_reason=reason or "crash",
                           detail=str(data["error"])[:500], elapsed_ms=elapsed())
    obj = data.get("objective")
    if not isinstance(obj, (int, float)):
        return EvalOutcome(False, fail_reason="bad_return",
                           detail=f"objective 非数值: {obj!r}", elapsed_ms=elapsed())
    return EvalOutcome(True, objective=float(obj), elapsed_ms=elapsed())


# ============ 裁判驱动评测(本地进化引擎用) ============
# 平台语义:裁判(可信,题目契约自带)掌握全部状态,按题目流式接口反复调用
# 候选函数并逐步校验合法性(越界/违约 → 大罚值);候选只实现启发式本身。
# judge_entry(instance, config, candidate_ns) -> objective | {"objective": ...}

_DRIVER_WORKER_SRC = '''# -*- coding: utf-8 -*-
"""裁判驱动评估工作进程:加载候选命名空间交给裁判,单次问答后退出。"""
import json, sys

def _load(path, name):
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()
    ns = {"__name__": name}
    exec(compile(src, path, "exec"), ns)
    return ns

def main():
    code_file, judge_file, judge_entry, entry = sys.argv[1:5]
    req = json.loads(sys.stdin.readline())
    try:
        ns = _load(code_file, "candidate")
    except Exception as e:
        sys.stdout.write(json.dumps({"error": f"load_error: {e!r}"}) + chr(10))
        return 2
    if entry and entry not in ns:
        sys.stdout.write(json.dumps({"error": "bad_entry: 缺少入口函数 " + entry}) + chr(10))
        return 2
    try:
        jns = _load(judge_file, "judge")
    except Exception as e:
        sys.stdout.write(json.dumps({"error": f"judge_load_error: {e!r}"}) + chr(10))
        return 5
    try:
        obj = jns[judge_entry](req.get("instance") or {}, req.get("config") or {}, ns)
    except Exception as e:
        sys.stdout.write(json.dumps({"error": f"judge_error: {e!r}"}) + chr(10))
        return 6
    if isinstance(obj, dict) and "objective" in obj:
        obj = obj["objective"]
    sys.stdout.write(json.dumps({"objective": obj}) + chr(10))
    return 0

if __name__ == "__main__":
    sys.exit(main())
'''


async def evaluate_solution(code: str, *, judge_source: str, judge_entry: str = "judge",
                            entry: str | None = None, instance: dict | None = None,
                            config: dict | None = None,
                            timeout: float = 10.0) -> EvalOutcome:
    """裁判驱动评测:judge 拿到候选命名空间,自行驱动流式接口并打分。"""
    if not judge_source.strip():
        return EvalOutcome(False, fail_reason="no_judge",
                           detail="题目契约缺少 judge 实现")
    start = time.monotonic()

    def elapsed() -> int:
        return int((time.monotonic() - start) * 1000)

    with tempfile.TemporaryDirectory(prefix="nova-evolve-") as tmp:
        code_file = str(Path(tmp) / "candidate.py")
        judge_file = str(Path(tmp) / "judge.py")
        worker_file = str(Path(tmp) / "worker.py")
        Path(code_file).write_text(code, encoding="utf-8")
        Path(judge_file).write_text(judge_source, encoding="utf-8")
        Path(worker_file).write_text(_DRIVER_WORKER_SRC, encoding="utf-8")
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, worker_file, code_file, judge_file, judge_entry,
                entry or "",
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except OSError as e:
            return EvalOutcome(False, fail_reason="crash", detail=str(e),
                               elapsed_ms=elapsed())
        try:
            payload = json.dumps({"instance": instance or {},
                                  "config": config or {}}).encode()
            out, _ = await asyncio.wait_for(proc.communicate(payload), timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return EvalOutcome(False, fail_reason="timeout",
                               detail=f"超过 {timeout}s", elapsed_ms=elapsed())
        except Exception as e:  # noqa: BLE001
            proc.kill()
            return EvalOutcome(False, fail_reason="crash", detail=str(e),
                               elapsed_ms=elapsed())

    if not out:
        return EvalOutcome(False, fail_reason="crash", detail="无输出",
                           elapsed_ms=elapsed())
    try:
        data = json.loads(out.decode("utf-8", "replace"))
    except ValueError:
        return EvalOutcome(False, fail_reason="bad_return",
                           detail=out[:200].decode("utf-8", "replace"),
                           elapsed_ms=elapsed())
    if "error" in data:
        reason = str(data["error"]).split(":", 1)[0]
        return EvalOutcome(False, fail_reason=reason or "crash",
                           detail=str(data["error"])[:500], elapsed_ms=elapsed())
    obj = data.get("objective")
    if not isinstance(obj, (int, float)):
        return EvalOutcome(False, fail_reason="bad_return",
                           detail=f"objective 非数值: {obj!r}", elapsed_ms=elapsed())
    return EvalOutcome(True, objective=float(obj), elapsed_ms=elapsed())
