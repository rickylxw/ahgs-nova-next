# -*- coding: utf-8 -*-
"""对战游戏:四子棋(重力落子 + 连线即胜,规格见仓库根 ARENA_GAMES.md §5.1)。

bot 入口约定(bot_contract):
    def move(board, me) -> int
        board: 长度 42 的列表,index = row*7+col,(0,0) 为左上,0=空 1/2=棋子
        me:    己方棋子(1 或 2)
        返回列号 0-6,棋子落入该列最下方空位;列满/越界/非 int 判负。

规则:重力落子;同色四连(横/竖/两斜)即胜;满盘无四连为平局。
"""
from __future__ import annotations

from typing import Any

from .base import Arena, ArenaError, BotProgram, GameRecord
from .runtime import BotProcess

COLS, ROWS = 7, 6

BOT_CONTRACT = """def move(board, me) -> int:
    board: 长度42列表, index = row*7+col, (0,0)左上, 0=空 1/2=双方棋子
    me:    己方棋子(1或2)
    返回:  列号0-6, 棋子落入该列最下方空位; 列满/越界/非int判负
    示例(挑最左未满列):
def move(board, me):
    for col in range(7):
        if board[col] == 0:   # 顶行(第0行)为空 => 该列未满
            return col
    return -1
"""

STARTER_CODE = """import random

def move(board, me):
    cols = [c for c in range(7) if board[c] == 0]
    return random.choice(cols) if cols else -1
"""


def _win_lines() -> tuple[tuple[int, ...], ...]:
    """全部四连线:横 24 + 竖 21 + 两斜 24 = 69 条。"""
    lines: list[tuple[int, ...]] = []
    for r in range(ROWS):
        for c in range(COLS - 3):
            lines.append(tuple(r * COLS + c + i for i in range(4)))
    for c in range(COLS):
        for r in range(ROWS - 3):
            lines.append(tuple((r + i) * COLS + c for i in range(4)))
    for r in range(ROWS - 3):
        for c in range(COLS - 3):
            lines.append(tuple((r + i) * COLS + (c + i) for i in range(4)))
    for r in range(3, ROWS):
        for c in range(COLS - 3):
            lines.append(tuple((r - i) * COLS + (c + i) for i in range(4)))
    return tuple(lines)


WIN_LINES = _win_lines()


class Connect4Arena(Arena):
    key = "connect4"
    display_name = "四子棋"
    bot_contract = BOT_CONTRACT
    starter_code = STARTER_CODE
    default_config = {"games_per_pairing": 4, "move_timeout": 3.0}
    min_bots = 2
    max_bots = 2
    board_shape = {"rows": ROWS, "cols": COLS}
    pieces = {"1": "●", "2": "○"}
    player_marks = {"1": "●", "2": "○"}
    labels = {
        "reason": {
            "win": "连成四子获胜",
            "draw": "满盘无四连,平局",
            "illegal": "非法落子判负",
            "timeout": "落子超时判负",
            "crash": "程序崩溃判负",
        },
        "outcome": {"ok": "落子", "illegal": "非法", "timeout": "超时", "crash": "崩溃"},
    }

    async def run_match(self, bots: list[BotProgram], config: dict[str, Any],
                        on_game=None) -> dict[str, Any]:
        if not (self.min_bots <= len(bots) <= self.max_bots):
            raise ArenaError("BOT_COUNT", "connect4 恰好需要 2 个 bot")
        cfg = self.merge_config(config)
        games_per_pairing = min(int(cfg.get("games_per_pairing", 4)), 20)
        move_timeout = float(cfg.get("move_timeout", 3.0))
        return await self.run_round_robin(
            bots, on_game,
            lambda a, b: self._play_one(a, b, move_timeout),
            games_per_pairing=games_per_pairing,
            report_config={"games_per_pairing": games_per_pairing,
                           "move_timeout": move_timeout},
        )

    # ---- 裁判 ----

    @staticmethod
    def _drop(board: list[int], col: int) -> int | None:
        """col 列重力落子,返回落点格下标;列满返回 None。"""
        for r in range(ROWS - 1, -1, -1):
            idx = r * COLS + col
            if board[idx] == 0:
                return idx
        return None

    @staticmethod
    def _has_won(board: list[int], piece: int) -> bool:
        return any(all(board[i] == piece for i in line) for line in WIN_LINES)

    async def _play_one(self, first: BotProgram, second: BotProgram,
                        move_timeout: float) -> GameRecord:
        players = [first, second]
        record = GameRecord(players=[first.id, second.id], first=first.id,
                            winner=None, reason="draw")
        board = [0] * (ROWS * COLS)
        turn = 0                                    # 0 = 先手棋子 1
        procs: list[BotProcess] = []

        try:
            for bot in players:
                proc = BotProcess(bot, timeout=move_timeout)
                procs.append(proc)
                await proc.start()

            while True:
                mover = players[turn]
                me = turn + 1
                try:
                    resp = await procs[turn].ask(
                        {"board": list(board), "me": me, "config": {}})
                    mv = resp.get("move")
                except ArenaError as e:
                    record.reason = ("timeout" if e.code == "BOT_TIMEOUT"
                                     else "crash")
                    record.winner = players[1 - turn].id
                    record.moves.append({"player": mover.id, "board": list(board),
                                         "outcome": record.reason, "detail": e.message})
                    return record

                idx = self._drop(board, mv) \
                    if isinstance(mv, int) and not isinstance(mv, bool) \
                    and 0 <= mv < COLS else None
                if idx is None:
                    record.reason = "illegal"
                    record.winner = players[1 - turn].id
                    record.moves.append({"player": mover.id, "board": list(board),
                                         "move": mv, "outcome": "illegal"})
                    return record

                board[idx] = me
                record.moves.append({"player": mover.id, "board": list(board),
                                     "move": mv, "outcome": "ok"})

                if self._has_won(board, me):
                    record.reason = "win"
                    record.winner = mover.id
                    return record
                if 0 not in board:
                    record.reason = "draw"
                    return record
                turn = 1 - turn
        finally:
            for p in procs:
                await p.close()
