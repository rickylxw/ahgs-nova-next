# -*- coding: utf-8 -*-
"""Bot 子进程运行时:每个 bot 一个持久子进程,JSON 行协议按步问答。

- 隔离:bot 崩溃/死循环不影响后端进程;按步超时后整个子进程被杀(判负)。
- 协议:parent → {"board":..., "me":..., "config":...}
        bot    → {"move": <int>} 或 {"error": "..."}
- 生产强化路径:替换本模块为 Docker 沙箱版(同一接口),Arena 无需改动。
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

from .base import ArenaError

_WORKER_SRC = '''# -*- coding: utf-8 -*-
"""bot 工作进程:加载用户源码,stdin/stdout JSON 行协议应答。"""
import json, sys

def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()
    ns = {"__name__": "bot"}
    exec(compile(src, path, "exec"), ns)
    return ns

def main():
    bot_file = sys.argv[1]
    try:
        ns = _load(bot_file)
    except Exception as e:  # 加载失败:立即以错误应答退出
        sys.stdout.write(json.dumps({"fatal": str(e)}) + "\\n")
        sys.stdout.flush()
        return 2
    sys.stdout.write(json.dumps({"ready": True}) + "\\n")
    sys.stdout.flush()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            move = ns["move"](req["board"], req["me"])
            resp = {"move": move}
        except Exception as e:
            resp = {"error": repr(e)}
        sys.stdout.write(json.dumps(resp) + "\\n")
        sys.stdout.flush()
    return 0

if __name__ == "__main__":
    sys.exit(main())
'''


class BotProcess:
    """一个 bot 的持久子进程会话。用完必须 close()(finally 保障)。"""

    def __init__(self, bot: "BotProgramLike", timeout: float = 3.0):
        self.bot = bot
        self.timeout = timeout
        self._proc: asyncio.subprocess.Process | None = None
        self._tmpdir: tempfile.TemporaryDirectory | None = None

    async def start(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory(prefix="nova-bot-")
        bot_file = str(Path(self._tmpdir.name) / "bot.py")
        Path(bot_file).write_text(self.bot.code, encoding="utf-8")
        worker_file = str(Path(self._tmpdir.name) / "worker.py")
        Path(worker_file).write_text(_WORKER_SRC, encoding="utf-8")
        self._proc = await asyncio.create_subprocess_exec(
            sys.executable, worker_file, bot_file,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        # 启动握手:worker 加载失败会立刻 fatal 退出
        first = await self._readline(self.timeout + 5)
        if first is None:
            raise ArenaError("BOT_CRASH",
                             f"bot「{self.bot.name}」加载失败或未响应")
        fatal = first.get("fatal")
        if fatal:
            raise ArenaError("BOT_CRASH",
                             f"bot「{self.bot.name}」加载失败: {fatal}")

    async def _readline(self, timeout: float) -> dict | None:
        try:
            raw = await asyncio.wait_for(self._proc.stdout.readline(), timeout)
        except asyncio.TimeoutError:
            return None
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            return None

    async def ask(self, payload: dict) -> dict:
        """向 bot 询问一步;超时/崩溃/非法应答统一抛 ArenaError(判负语义)。"""
        if self._proc is None or self._proc.returncode is not None:
            raise ArenaError("BOT_CRASH", f"bot「{self.bot.name}」进程已退出")
        try:
            self._proc.stdin.write((json.dumps(payload) + "\n").encode())
            await self._proc.stdin.drain()
        except (BrokenPipeError, RuntimeError) as e:
            raise ArenaError("BOT_CRASH", f"bot「{self.bot.name}」通信失败: {e}") from e
        resp = await self._readline(self.timeout)
        if resp is None:
            await self.close()
            raise ArenaError("BOT_TIMEOUT",
                             f"bot「{self.bot.name}」超时({self.timeout}s)")
        if "error" in resp:
            raise ArenaError("BOT_ERROR",
                             f"bot「{self.bot.name}」抛出异常: {resp['error']}")
        return resp

    async def close(self) -> None:
        if self._proc is not None and self._proc.returncode is None:
            try:
                self._proc.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._proc.kill()
        self._proc = None
        if self._tmpdir is not None:
            self._tmpdir.cleanup()
            self._tmpdir = None


class BotProgramLike:  # 结构化鸭子类型标注(base.BotProgram),避免循环导入
    id: int
    name: str
    code: str
