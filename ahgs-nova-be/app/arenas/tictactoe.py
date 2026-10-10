# -*- coding: utf-8 -*-
"""参考 Arena:井字棋(证明扩展点闭环的最小完整实现)。

bot 入口约定(bot_contract):
    def move(board, me) -> int
        board: 长度 9 的列表,0=空 1=先手方落子 2=后手方落子
        me:    己方棋子(1 或 2)
        返回 0-8 的落子下标;非法/超时/异常直接判负。

对局规则:每对 bot 交互 games 局(轮换先手);犯规/超时/崩溃即负;
满盘无胜负为平局。多方 bot 两两循环对阵(赛制助手 Arena.run_round_robin)。
"""
from __future__ import annotations

from typing import Any

from .base import Arena, ArenaError, BotProgram, GameRecord
from .runtime import BotProcess

WIN_LINES = ((0, 1, 2), (3, 4, 5), (6, 7, 8),
             (0, 3, 6), (1, 4, 7), (2, 5, 8),
             (0, 4, 8), (2, 4, 6))

BOT_CONTRACT = """def move(board, me) -> int:
    board: 长度9列表(0空/1/2), me: 己方棋子(1或2), 返回 0-8 的落子下标。
    示例:
def move(board, me):
    for i, v in enumerate(board):
        if v == 0:
            return i
    return -1
"""

STARTER_CODE = """def move(board, me):
    for i, v in enumerate(board):
        if v == 0:
            return i
    return -1
"""


class TicTacToeArena(Arena):
    key = "tictactoe"
    display_name = "井字棋"
    bot_contract = BOT_CONTRACT
    starter_code = STARTER_CODE
    default_config = {"games_per_pairing": 4, "move_timeout": 3.0}
    min_bots = 2
    max_bots = 2
    board_shape = {"rows": 3, "cols": 3}
    pieces = {"1": "X", "2": "O"}
    player_marks = {"1": "X", "2": "O"}
    labels = {
        "reason": {
            "win": "连成一线获胜",
            "draw": "满盘无胜负,平局",
            "illegal": "非法落子判负",
            "timeout": "落子超时判负",
            "crash": "程序崩溃判负",
        },
        "outcome": {"ok": "落子", "illegal": "非法", "timeout": "超时", "crash": "崩溃"},
    }

    async def run_match(self, bots: list[BotProgram], config: dict[str, Any],
                        on_game=None) -> dict[str, Any]:
        if not (self.min_bots <= len(bots) <= self.max_bots):
            raise ArenaError("BOT_COUNT", "tictactoe 恰好需要 2 个 bot")
        cfg = self.merge_config(config)
        games_per_pairing = min(int(cfg.get("games_per_pairing", 4)), 100)
        move_timeout = float(cfg.get("move_timeout", 3.0))
        return await self.run_round_robin(
            bots, on_game,
            lambda a, b: self._play_one(a, b, move_timeout),
            games_per_pairing=games_per_pairing,
            report_config={"games_per_pairing": games_per_pairing,
                           "move_timeout": move_timeout},
        )

    # ---- 裁判 ----

    async def _play_one(self, first: BotProgram, second: BotProgram,
                        move_timeout: float) -> GameRecord:
        players = [first, second]
        record = GameRecord(players=[first.id, second.id], first=first.id,
                            winner=None, reason="draw")
        board = [0] * 9
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
                        {"board": board, "me": me, "config": {}})
                    mv = resp.get("move")
                except ArenaError as e:
                    record.reason = ("timeout" if e.code == "BOT_TIMEOUT"
                                     else "crash")
                    record.winner = players[1 - turn].id
                    record.moves.append({"player": mover.id, "board": list(board),
                                         "outcome": record.reason, "detail": e.message})
                    return record

                if not isinstance(mv, int) or not (0 <= mv < 9) or board[mv] != 0:
                    record.reason = "illegal"
                    record.winner = players[1 - turn].id
                    record.moves.append({"player": mover.id, "board": list(board),
                                         "move": mv, "outcome": "illegal"})
                    return record

                board[mv] = me
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

    @staticmethod
    def _has_won(board: list[int], piece: int) -> bool:
        return any(board[a] == piece and board[b] == piece and board[c] == piece
                   for a, b, c in WIN_LINES)
