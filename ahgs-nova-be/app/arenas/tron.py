# -*- coding: utf-8 -*-
"""对战游戏:光轮 Tron(轮流移动 + 位置碰撞,规格见仓库根 ARENA_GAMES.md §6.1)。

bot 入口约定(bot_contract):
    def move(board, me) -> int
        board: 长度 225 的列表(15×15),index = row*15+col
               0=空 1/2=双方车痕 3/4=双方车头(3 为 1 号车头)
        me:    己方编号(1 或 2,整局固定;起点 1 在 (7,0),2 在 (7,14))
        返回:  0上 1下 2左 3右;撞墙/撞痕/出界即出局(非非法)。

规则:车头所过之处留下车痕,任何人无路可走即出局;棋盘走满无人出局为平局。
设计注:协议不向 bot 传历史,车头以 3/4 编码直接可读,bot 无需自行记忆定位。
"""
from __future__ import annotations

from typing import Any

from .base import Arena, ArenaError, BotProgram, GameRecord
from .runtime import BotProcess

SIZE = 15

DELTAS = ((-1, 0), (1, 0), (0, -1), (0, 1))     # 上 下 左 右

BOT_CONTRACT = """def move(board, me) -> int:
    board: 长度225列表(15x15), index = row*15+col
           0=空 1/2=双方车痕 3/4=双方车头(3 为 1 号车头)
    me:    己方编号(1或2); 起点 1 在 (7,0), 2 在 (7,14)
    返回:  0上 1下 2左 3右; 撞墙/撞痕/出界即出局
    规则:  无路可走即输, 棋盘走满无人出局为平局
"""

STARTER_CODE = """import random

DELTAS = ((-1, 0), (1, 0), (0, -1), (0, 1))  # 上 下 左 右
N = 15

def move(board, me):
    head = board.index(me + 2)               # 3/4 = 双方车头
    r, c = divmod(head, N)
    opts = [d for d, (dr, dc) in enumerate(DELTAS)
            if 0 <= r + dr < N and 0 <= c + dc < N
            and board[(r + dr) * N + (c + dc)] == 0]
    return random.choice(opts) if opts else 0
"""


class TronArena(Arena):
    key = "tron"
    display_name = "光轮"
    bot_contract = BOT_CONTRACT
    starter_code = STARTER_CODE
    default_config = {"games_per_pairing": 4, "move_timeout": 2.0}
    min_bots = 2
    max_bots = 2
    board_shape = {"rows": SIZE, "cols": SIZE}
    pieces = {"1": "■", "2": "■", "3": "◆", "4": "◆"}
    player_marks = {"1": "◆", "2": "◆"}
    cell_classes = {"1": "x", "2": "o", "3": "x", "4": "o"}
    labels = {
        "reason": {
            "win": "对手出局获胜",
            "draw": "棋盘走满,平局",
            "illegal": "非法动作判负",
            "timeout": "超步判负",
            "crash": "程序崩溃判负",
        },
        "outcome": {"ok": "移动", "hit": "撞墙出局",
                    "illegal": "非法", "timeout": "超时", "crash": "崩溃"},
    }

    async def run_match(self, bots: list[BotProgram], config: dict[str, Any],
                        on_game=None) -> dict[str, Any]:
        if not (self.min_bots <= len(bots) <= self.max_bots):
            raise ArenaError("BOT_COUNT", "tron 恰好需要 2 个 bot")
        cfg = self.merge_config(config)
        games_per_pairing = min(int(cfg.get("games_per_pairing", 4)), 20)
        move_timeout = float(cfg.get("move_timeout", 2.0))
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
        board = [0] * (SIZE * SIZE)
        board[7 * SIZE] = 3                          # (7,0)  1 号车头
        board[7 * SIZE + SIZE - 1] = 4               # (7,14) 2 号车头
        heads = [7 * SIZE, 7 * SIZE + SIZE - 1]
        turn = 0
        procs: list[BotProcess] = []

        try:
            for bot in players:
                proc = BotProcess(bot, timeout=move_timeout)
                procs.append(proc)
                await proc.start()

            while True:
                mover = players[turn]
                me = turn + 1
                snap = list(board)
                try:
                    resp = await procs[turn].ask(
                        {"board": snap, "me": me, "config": {}})
                    mv = resp.get("move")
                except ArenaError as e:
                    record.reason = ("timeout" if e.code == "BOT_TIMEOUT"
                                     else "crash")
                    record.winner = players[1 - turn].id
                    record.moves.append({"player": mover.id, "board": snap,
                                         "outcome": record.reason, "detail": e.message})
                    return record

                if (not isinstance(mv, int) or isinstance(mv, bool)
                        or not (0 <= mv < 4)):
                    record.reason = "illegal"
                    record.winner = players[1 - turn].id
                    record.moves.append({"player": mover.id, "board": snap,
                                         "move": mv, "outcome": "illegal"})
                    return record

                dr, dc = DELTAS[mv]
                r, c = divmod(heads[turn], SIZE)
                rr, cc = r + dr, c + dc
                if not (0 <= rr < SIZE and 0 <= cc < SIZE) \
                        or board[rr * SIZE + cc] != 0:
                    # 撞墙/撞痕/出界:玩法性出局(reason=win),非非法动作
                    record.reason = "win"
                    record.winner = players[1 - turn].id
                    record.moves.append({
                        "player": mover.id, "board": snap,
                        "move": rr * SIZE + cc if 0 <= rr < SIZE and 0 <= cc < SIZE else None,
                        "outcome": "hit", "detail": "撞墙"})
                    return record

                board[heads[turn]] = me              # 旧头留痕
                heads[turn] = rr * SIZE + cc
                board[heads[turn]] = me + 2          # 新头
                record.moves.append({"player": mover.id, "board": list(board),
                                     "move": heads[turn], "outcome": "ok"})

                if 0 not in board:
                    record.reason = "draw"
                    return record
                turn = 1 - turn
        finally:
            for p in procs:
                await p.close()
