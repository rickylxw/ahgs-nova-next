# -*- coding: utf-8 -*-
"""对战游戏:黑白棋(终局计子 + 自动 pass,规格见仓库根 ARENA_GAMES.md §5.3)。

bot 入口约定(bot_contract):
    def move(board, me) -> int
        board: 长度 64 的列表,index = row*8+col,(0,0) 为左上,0=空 1=黑(先手) 2=白
        me:    己方棋子(1 或 2,整局固定)
        返回 0-63 的合法翻转点;不合法判负。
        无合法着法时裁判自动 pass(不会询问该 bot),双方连续无着即终局计子。

规则:夹住对方棋子即翻转;子多者胜(平子罕见);pass 记 outcome="pass" 的步。
"""
from __future__ import annotations

from typing import Any

from .base import Arena, ArenaError, BotProgram, GameRecord
from .runtime import BotProcess

SIZE = 8

DIRS = ((0, 1), (0, -1), (1, 0), (-1, 0), (1, 1), (1, -1), (-1, 1), (-1, -1))

BOT_CONTRACT = """def move(board, me) -> int:
    board: 长度64列表(8x8), index = row*8+col, 0=空 1=黑(先手) 2=白
    me:    己方棋子(1或2, 整局固定)
    返回:  0-63, 必须是能翻转至少一枚对方棋子的空格; 不合法判负
    说明:  无合法着法时裁判自动pass(不会询问你), 双方均无着法即终局计子
"""

STARTER_CODE = """def move(board, me):
    opp, n = 3 - me, 8
    for idx in range(64):
        if board[idx] != 0:
            continue
        r, c = divmod(idx, n)
        for dr, dc in ((0,1),(0,-1),(1,0),(-1,0),(1,1),(1,-1),(-1,1),(-1,-1)):
            i, j, k = r + dr, c + dc, 0
            while 0 <= i < n and 0 <= j < n and board[i*n+j] == opp:
                i += dr; j += dc; k += 1
            if k and 0 <= i < n and 0 <= j < n and board[i*n+j] == me:
                return idx
    return -1
"""


class ReversiArena(Arena):
    key = "reversi"
    display_name = "黑白棋"
    bot_contract = BOT_CONTRACT
    starter_code = STARTER_CODE
    default_config = {"games_per_pairing": 4, "move_timeout": 3.0}
    min_bots = 2
    max_bots = 2
    board_shape = {"rows": SIZE, "cols": SIZE}
    pieces = {"1": "●", "2": "○"}
    player_marks = {"1": "●", "2": "○"}
    labels = {
        "reason": {
            "win": "终局计子获胜",
            "draw": "终局平子",
            "illegal": "非法落子判负",
            "timeout": "落子超时判负",
            "crash": "程序崩溃判负",
        },
        "outcome": {"ok": "落子", "pass": "无子可下,自动跳手",
                    "illegal": "非法", "timeout": "超时", "crash": "崩溃"},
    }

    async def run_match(self, bots: list[BotProgram], config: dict[str, Any],
                        on_game=None) -> dict[str, Any]:
        if not (self.min_bots <= len(bots) <= self.max_bots):
            raise ArenaError("BOT_COUNT", "reversi 恰好需要 2 个 bot")
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
    def _flips_for(board: list[int], idx: int, me: int) -> list[int]:
        """idx 落子能翻转的对方棋子格列表;空列表 = 非法点。"""
        if board[idx] != 0:
            return []
        opp = 3 - me
        r, c = divmod(idx, SIZE)
        flips: list[int] = []
        for dr, dc in DIRS:
            line, i, j = [], r + dr, c + dc
            while 0 <= i < SIZE and 0 <= j < SIZE and board[i * SIZE + j] == opp:
                line.append(i * SIZE + j)
                i += dr
                j += dc
            if line and 0 <= i < SIZE and 0 <= j < SIZE and board[i * SIZE + j] == me:
                flips.extend(line)
        return flips

    @classmethod
    def _legal_moves(cls, board: list[int], me: int) -> dict[int, list[int]]:
        return {idx: flips for idx in range(SIZE * SIZE)
                if (flips := cls._flips_for(board, idx, me))}

    async def _play_one(self, first: BotProgram, second: BotProgram,
                        move_timeout: float) -> GameRecord:
        players = [first, second]
        record = GameRecord(players=[first.id, second.id], first=first.id,
                            winner=None, reason="draw")
        board = [0] * (SIZE * SIZE)
        board[27], board[36] = 2, 2                 # (3,3) / (4,4) = 白
        board[28], board[35] = 1, 1                 # (3,4) / (4,3) = 黑(先手)
        turn = 0
        passes = 0
        procs: list[BotProcess] = []

        try:
            for bot in players:
                proc = BotProcess(bot, timeout=move_timeout)
                procs.append(proc)
                await proc.start()

            while True:
                mover = players[turn]
                me = turn + 1
                legal = self._legal_moves(board, me)
                if not legal:
                    # 自动 pass;双方连续无着 → 终局计子
                    passes += 1
                    record.moves.append({"player": mover.id, "board": list(board),
                                         "outcome": "pass", "detail": "无合法着法"})
                    if passes >= 2:
                        self._settle_by_count(record, board)
                        return record
                    turn = 1 - turn
                    continue
                passes = 0
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
                        or mv not in legal):
                    record.reason = "illegal"
                    record.winner = players[1 - turn].id
                    record.moves.append({"player": mover.id, "board": list(board),
                                         "move": mv, "outcome": "illegal"})
                    return record

                board[mv] = me
                for f in legal[mv]:
                    board[f] = me
                record.moves.append({"player": mover.id, "board": list(board),
                                     "move": mv, "outcome": "ok"})
                turn = 1 - turn
        finally:
            for p in procs:
                await p.close()

    @staticmethod
    def _settle_by_count(record: GameRecord, board: list[int]) -> None:
        """终局计子:players[0] 执黑(1)。平子保留 reason="draw"。"""
        black, white = board.count(1), board.count(2)
        if black == white:
            record.reason = "draw"
            return
        record.reason = "win"
        record.winner = record.players[0] if black > white else record.players[1]
        if record.moves:
            record.moves[-1]["detail"] = f"{black}:{white} 子数比"
