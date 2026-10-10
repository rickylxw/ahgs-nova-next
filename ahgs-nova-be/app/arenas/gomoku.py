# -*- coding: utf-8 -*-
"""对战游戏:五子棋(15×15 自由规则,规格见仓库根 ARENA_GAMES.md §5.2)。

bot 入口约定(bot_contract):
    def move(board, me) -> int
        board: 长度 225 的列表,index = row*15+col,(0,0) 为左上,0=空 1/2=棋子
        me:    己方棋子(1=先手黑, 2=后手白)
        返回 0-224 的落子下标;占用/越界/非 int 判负。

规则:自由规则无禁手,横/竖/斜连成 5 子及以上即胜(长连亦胜);满盘为平局。
"""
from __future__ import annotations

from typing import Any

from .base import Arena, ArenaError, BotProgram, GameRecord
from .runtime import BotProcess

SIZE = 15

BOT_CONTRACT = """def move(board, me) -> int:
    board: 长度225列表(15x15), index = row*15+col, 0=空 1/2=棋子
    me:    己方棋子(1=先手黑, 2=后手白)
    规则:  自由规则无禁手, 横/竖/斜连成5子及以上即胜(长连亦胜)
    返回:  0-224 落子下标; 占用/越界/非int判负
"""

STARTER_CODE = """import random

def move(board, me):
    empties = [i for i, v in enumerate(board) if v == 0]
    return random.choice(empties) if empties else 0
"""


class GomokuArena(Arena):
    key = "gomoku"
    display_name = "五子棋"
    bot_contract = BOT_CONTRACT
    starter_code = STARTER_CODE
    default_config = {"games_per_pairing": 4, "move_timeout": 5.0}
    min_bots = 2
    max_bots = 2
    board_shape = {"rows": SIZE, "cols": SIZE}
    pieces = {"1": "●", "2": "○"}
    player_marks = {"1": "●", "2": "○"}
    labels = {
        "reason": {
            "win": "连成五子及以上获胜",
            "draw": "满盘平局",
            "illegal": "非法落子判负",
            "timeout": "落子超时判负",
            "crash": "程序崩溃判负",
        },
        "outcome": {"ok": "落子", "illegal": "非法", "timeout": "超时", "crash": "崩溃"},
    }

    async def run_match(self, bots: list[BotProgram], config: dict[str, Any],
                        on_game=None) -> dict[str, Any]:
        if not (self.min_bots <= len(bots) <= self.max_bots):
            raise ArenaError("BOT_COUNT", "gomoku 恰好需要 2 个 bot")
        cfg = self.merge_config(config)
        # 大棋盘重棋类:gpp 上限 8,控制回放体积与子进程开销(§3.1)
        games_per_pairing = min(int(cfg.get("games_per_pairing", 4)), 8)
        move_timeout = float(cfg.get("move_timeout", 5.0))
        return await self.run_round_robin(
            bots, on_game,
            lambda a, b: self._play_one(a, b, move_timeout),
            games_per_pairing=games_per_pairing,
            report_config={"games_per_pairing": games_per_pairing,
                           "move_timeout": move_timeout},
        )

    # ---- 裁判 ----

    @staticmethod
    def _has_won(board: list[int], idx: int, piece: int) -> bool:
        """刚落在 idx 的 piece 是否连成 5 子及以上(四轴双向计数)。"""
        row, col = divmod(idx, SIZE)
        for dr, dc in ((0, 1), (1, 0), (1, 1), (1, -1)):
            count = 1
            for sign in (1, -1):
                r, c = row + dr * sign, col + dc * sign
                while 0 <= r < SIZE and 0 <= c < SIZE and board[r * SIZE + c] == piece:
                    count += 1
                    r += dr * sign
                    c += dc * sign
            if count >= 5:
                return True
        return False

    async def _play_one(self, first: BotProgram, second: BotProgram,
                        move_timeout: float) -> GameRecord:
        players = [first, second]
        record = GameRecord(players=[first.id, second.id], first=first.id,
                            winner=None, reason="draw")
        board = [0] * (SIZE * SIZE)
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

                if (not isinstance(mv, int) or isinstance(mv, bool)
                        or not (0 <= mv < SIZE * SIZE) or board[mv] != 0):
                    record.reason = "illegal"
                    record.winner = players[1 - turn].id
                    record.moves.append({"player": mover.id, "board": list(board),
                                         "move": mv, "outcome": "illegal"})
                    return record

                board[mv] = me
                record.moves.append({"player": mover.id, "board": list(board),
                                     "move": mv, "outcome": "ok"})

                if self._has_won(board, mv, me):
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
