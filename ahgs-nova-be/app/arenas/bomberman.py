# -*- coding: utf-8 -*-
"""对战游戏:炸弹人(回合制布雷对轰,支持 2-4 人同局;规格见仓库根 ARENA_GAMES.md §6.2)。

bot 入口约定(bot_contract):
    def move(board, me) -> int
        board: dict 视图
            cells:   长度 169 的列表,index = row*13+col
                     0空地 1硬墙 2软墙(可炸毁) 3炸弹 4火焰 5/6/7/8=各玩家(踩弹时仍显示玩家码)
            players: 各玩家位置(格下标,按编号序;players[me-1] 是自己)
            bombs:   [{"cell": 下标, "fuse": 剩余回合数, "owner": 玩家编号}](脚下有弹以本列表为准)
        me:    己方编号(1 起);出生点 2 人=(1,1)/(11,11) 对角,3 人=(1,1)/(1,11)/(11,6),4 人=四角
        返回:  0上 1下 2左 3右 4原地布雷 5原地不动

规则:走入火焰 / 被爆炸波及即出局(死亡即离场,多人局不结束),仅剩 1 人获胜,
全灭或回合耗尽平局;任何两名玩家不可占据同一格(走进对方所在格 = 非法);
撞墙/撞弹/越界/违规布雷判非法;引信每回合(全部存活玩家各行动一次)-1,
十字半径爆炸可炸开软墙并连锁引爆。随机性:布局由 config["seed"] 驱动(缺省生成并
写回 result.config),逐局派生,可复现。双人局走 pairwise 循环赛(legacy 语义不变)。
"""
from __future__ import annotations

import random
import secrets
from typing import Any

from .base import Arena, ArenaError, BotProgram, GameRecord
from .runtime import BotProcess

N = 13
FLOOR, HARD, SOFT, BOMB, FLAME = 0, 1, 2, 3, 4
P1, P2, P3, P4 = 5, 6, 7, 8

DELTAS = ((-1, 0), (1, 0), (0, -1), (0, 1))     # 上 下 左 右
MOVE_UP, MOVE_DOWN, MOVE_LEFT, MOVE_RIGHT = range(4)
PLANT, PASS = 4, 5

# 各人数的出生点(编号序);3 人取三处等距感最好的点位
SPAWNS: dict[int, list[tuple[int, int]]] = {
    2: [(1, 1), (11, 11)],
    3: [(1, 1), (1, 11), (11, 6)],
    4: [(1, 1), (1, 11), (11, 1), (11, 11)],
}

BOT_CONTRACT = """def move(board, me) -> int:
    board: dict 视图
        cells:   长度169列表, index = row*13+col: 0空地 1硬墙 2软墙(可炸毁) 3炸弹 4火焰 5/6/7/8=各玩家
        players: 各玩家位置(格下标, 按编号序, players[me-1] 是自己)
        bombs:   [{"cell": 下标, "fuse": 剩余回合数, "owner": 玩家编号}](脚下有弹以本列表为准)
    me:    己方编号(1 起); 出生点 2 人=对角 (1,1)/(11,11), 3 人=(1,1)/(1,11)/(11,6), 4 人=四角
    返回:  0上 1下 2左 3右 4原地布雷 5原地不动
    规则:  走入火焰/被爆炸波及即出局, 仅剩 1 人获胜, 全灭或回合耗尽平局;
          不可走进任何玩家所在格(独占); 撞墙/撞弹/越界/违规布雷判非法;
          引信每回合-1, 十字爆炸可炸开软墙并连锁引爆
"""

STARTER_CODE = """import random

DELTAS = ((-1, 0), (1, 0), (0, -1), (0, 1))  # 上 下 左 右
N = 13

def move(board, me):
    cells = board["cells"]
    r, c = divmod(board["players"][me - 1], N)
    others = [p for i, p in enumerate(board["players"]) if i != me - 1]
    walks = []
    for d, (dr, dc) in enumerate(DELTAS):
        rr, cc = r + dr, c + dc
        if 0 <= rr < N and 0 <= cc < N:
            i = rr * N + cc
            if i not in others and cells[i] == 0:      # 只走空地,不进火焰不撞人
                walks.append(d)
    if walks:
        return random.choice(walks)
    if not any(b["cell"] == r * N + c for b in board["bombs"]):
        return 4                                # 无处可走就地布雷
    return 5
"""


def _layout(rng: random.Random, spawns: list[tuple[int, int]]) -> list[int]:
    """边框 + 柱状硬墙,软墙按 0.45 概率随机填充(各出生点及其通路格清空)。"""
    cells = [FLOOR] * (N * N)
    for r in range(N):
        for c in range(N):
            if r in (0, N - 1) or c in (0, N - 1) or (r % 2 == 0 and c % 2 == 0):
                cells[r * N + c] = HARD
    safe = set()
    for r, c in spawns:
        safe.add((r, c))
        for dr, dc in DELTAS:
            rr, cc = r + dr, c + dc
            if 0 < rr < N - 1 and 0 < cc < N - 1:
                safe.add((rr, cc))
    for r in range(1, N - 1):
        for c in range(1, N - 1):
            if cells[r * N + c] == FLOOR and (r, c) not in safe \
                    and rng.random() < 0.45:
                cells[r * N + c] = SOFT
    return cells


class BombermanArena(Arena):
    key = "bomberman"
    display_name = "炸弹人"
    bot_contract = BOT_CONTRACT
    starter_code = STARTER_CODE
    default_config = {"games_per_pairing": 2, "games": 2, "move_timeout": 3.0,
                      "fuse": 3, "radius": 2, "max_bombs": 2,
                      "max_rounds": 100, "seed": None}
    min_bots = 2
    max_bots = 4
    board_shape = {"rows": N, "cols": N}
    pieces = {"1": "▩", "2": "▦", "3": "◉", "4": "✸",
              "5": "◆", "6": "◆", "7": "◆", "8": "◆"}
    cell_classes = {"1": "wall", "2": "soft", "3": "bomb", "4": "flame",
                    "5": "x", "6": "o", "7": "p3", "8": "p4"}
    player_marks = {"1": "◆", "2": "◆", "3": "◆", "4": "◆"}
    labels = {
        "reason": {
            "win": "对手出局获胜",
            "draw": "同归于尽或回合耗尽,平局",
            "illegal": "非法动作判负",
            "timeout": "超步判负",
            "crash": "程序崩溃判负",
        },
        "outcome": {"ok": "行动", "hit": "阵亡",
                    "illegal": "非法", "timeout": "超时", "crash": "崩溃"},
    }

    async def run_match(self, bots: list[BotProgram], config: dict[str, Any],
                        on_game=None) -> dict[str, Any]:
        if not (self.min_bots <= len(bots) <= self.max_bots):
            raise ArenaError("BOT_COUNT", "bomberman 需要 2-4 个 bot")
        cfg = self.merge_config(config)
        move_timeout = float(cfg.get("move_timeout", 3.0))
        fuse = max(1, min(8, int(cfg.get("fuse", 3))))
        radius = max(1, min(5, int(cfg.get("radius", 2))))
        max_bombs = max(1, min(5, int(cfg.get("max_bombs", 2))))
        max_rounds = max(10, min(500, int(cfg.get("max_rounds", 100))))
        # 布局随机性:seed 缺省生成并写回(§3.4 可复现);逐局派生子种子
        base_seed = int(cfg.get("seed") or secrets.randbits(32))
        report_config = {"move_timeout": move_timeout, "fuse": fuse,
                         "radius": radius, "max_bombs": max_bombs,
                         "max_rounds": max_rounds, "seed": base_seed}

        if len(bots) == 2:
            # legacy:pairwise 循环赛(组内轮换先手),行为被回归测试钉死
            games_per_pairing = min(int(cfg.get("games_per_pairing", 2)), 8)
            report_config["games_per_pairing"] = games_per_pairing
            game_seq = iter(range(games_per_pairing))

            def play(a, b):
                seed = f"nova-bomber-{base_seed}-{next(game_seq)}"
                return self._play_one(a, b, move_timeout, fuse, radius,
                                      max_bombs, max_rounds, seed)

            return await self.run_round_robin(
                bots, on_game, play,
                games_per_pairing=games_per_pairing,
                report_config=report_config,
            )

        # ---- 多人同局(3-4 人):全员进场,每局轮换先手 ----
        games_count = max(1, min(8, int(cfg.get("games", 2))))
        report_config["games"] = games_count
        scores = {b.id: {"win": 0, "loss": 0, "draw": 0} for b in bots}
        games: list[dict] = []
        for game_no in range(games_count):
            cut = game_no % len(bots)
            order = bots[cut:] + bots[:cut]
            record = await self._play_multi(
                order, move_timeout, fuse, radius, max_bombs, max_rounds,
                f"nova-bomber-{base_seed}-{game_no}")
            games.append(record.as_dict())
            for gi, group in enumerate(record.ranking):
                key = "win" if gi == 0 else ("loss" if gi == len(record.ranking) - 1
                                             else "draw")
                for pid in group:
                    scores[pid][key] += 1
            if on_game is not None:
                await on_game(record)
        return {"arena": self.key, "config": report_config,
                "games": games, "scores": scores}

    # ---- 裁判 ----

    @staticmethod
    def _blast(cells: list[int], bomb_cells: set[int], cell: int,
               radius: int) -> tuple[set[int], list[int], list[int]]:
        """以 cell 为中心的十字爆炸。返回 (火焰格, 炸毁软墙, 连锁引爆的炸弹格)。"""
        flames = {cell}
        destroyed: list[int] = []
        chain: list[int] = []
        r0, c0 = divmod(cell, N)
        for dr, dc in DELTAS:
            for k in range(1, radius + 1):
                r, c = r0 + dr * k, c0 + dc * k
                if not (0 <= r < N and 0 <= c < N):
                    break
                i = r * N + c
                if cells[i] == HARD:
                    break
                flames.add(i)
                if cells[i] == SOFT:
                    destroyed.append(i)
                    break
                if i in bomb_cells and i != cell:
                    chain.append(i)
                    break
        return flames, destroyed, chain

    @staticmethod
    def _snapshot(cells: list[int], bombs: list[dict], flames: set[int],
                  pos: list[int]) -> dict:
        grid = list(cells)
        for f in flames:
            grid[f] = FLAME
        for b in bombs:
            grid[b["cell"]] = BOMB
        for i, p in enumerate(pos):
            grid[p] = P1 + i
        return {"cells": grid, "players": list(pos),
                "bombs": [dict(b) for b in bombs]}

    def _explode_phase(self, cells: list[int], bombs: list[dict],
                       radius: int) -> set[int]:
        """引信归零的炸弹连锁爆炸;返回本回合火焰格(覆盖旧火焰)。"""
        queue = [b for b in bombs if b["fuse"] <= 0]
        bomb_at = {b["cell"]: b for b in bombs}
        done: set[int] = set()
        flames: set[int] = set()
        while queue:
            b = queue.pop()
            if b["cell"] in done:
                continue
            done.add(b["cell"])
            f, destroyed, chain = self._blast(cells, set(bomb_at), b["cell"], radius)
            for i in destroyed:
                cells[i] = FLOOR
            flames |= f
            for ci in chain:
                if ci not in done:
                    queue.append(bomb_at[ci])
        bombs[:] = [b for b in bombs if b["cell"] not in done]
        return flames

    def _apply_action(self, cells: list[int], bombs: list[dict],
                      pos: list[int], pi: int, mv,
                      fuse: int, max_bombs: int) -> tuple[int, str | None]:
        """校验并执行行动;返回 (落点格, 错误)。err 非 None 即非法。

        格子独占:不可走进任何其他玩家所在格(2-4 人一律适用)。
        """
        me = pi + 1
        if not isinstance(mv, int) or isinstance(mv, bool) or not (0 <= mv <= 5):
            return -1, "bad_action"
        if mv in (MOVE_UP, MOVE_DOWN, MOVE_LEFT, MOVE_RIGHT):
            dr, dc = DELTAS[mv]
            r, c = divmod(pos[pi], N)
            rr, cc = r + dr, c + dc
            if not (0 <= rr < N and 0 <= cc < N):
                return -1, "oob"
            target = rr * N + cc
            if any(target == pos[j] for j in range(len(pos)) if j != pi):
                return -1, "occupied_by_player"
            if cells[target] in (HARD, SOFT, BOMB):
                return -1, "blocked"
            pos[pi] = target
            return target, None
        if mv == PLANT:
            if any(b["cell"] == pos[pi] for b in bombs):
                return -1, "bomb_here"
            if sum(1 for b in bombs if b["owner"] == me) >= max_bombs:
                return -1, "bomb_limit"
            bombs.append({"cell": pos[pi], "fuse": fuse, "owner": me})
            return pos[pi], None
        return pos[pi], None                             # PASS

    @staticmethod
    def _finish(record: GameRecord, players: list[BotProgram],
                alive: list[int], dead_groups: list[list[int]]) -> None:
        """按存活组(并列)+ 死亡组倒序落名次;仅剩 1 人为胜,否则平。"""
        record.ranking = [[players[pi].id for pi in alive]] + [
            [players[pi].id for pi in g] for g in reversed(dead_groups)]
        if len(alive) == 1:
            record.reason = "win"
            record.winner = players[alive[0]].id
        else:
            record.reason = "draw"

    async def _play_one(self, first: BotProgram, second: BotProgram,
                        move_timeout: float, fuse: int, radius: int,
                        max_bombs: int, max_rounds: int,
                        rng_seed: str) -> GameRecord:
        """双人局(legacy 路径,与 run_round_robin 配对;行为被回归测试钉死)。"""
        players = [first, second]
        record = GameRecord(players=[first.id, second.id], first=first.id,
                            winner=None, reason="draw")
        rng = random.Random(rng_seed)
        cells = _layout(rng, SPAWNS[2])
        pos = [1 * N + 1, (N - 2) * N + (N - 2)]     # 出生点 (1,1) / (11,11)
        bombs: list[dict] = []
        flames: set[int] = set()
        procs: list[BotProcess] = []

        try:
            for bot in players:
                proc = BotProcess(bot, timeout=move_timeout)
                procs.append(proc)
                await proc.start()

            for _round in range(max_rounds):
                for pi in (0, 1):
                    mover = players[pi]
                    me = pi + 1
                    snap = self._snapshot(cells, bombs, flames, pos)
                    try:
                        resp = await procs[pi].ask(
                            {"board": snap, "me": me, "config": {}})
                        mv = resp.get("move")
                    except ArenaError as e:
                        record.reason = ("timeout" if e.code == "BOT_TIMEOUT"
                                         else "crash")
                        record.winner = players[1 - pi].id
                        record.moves.append({"player": mover.id, "board": snap,
                                             "outcome": record.reason,
                                             "detail": e.message})
                        return record

                    resulting, err = self._apply_action(
                        cells, bombs, pos, pi, mv, fuse, max_bombs)
                    if err is not None:
                        record.reason = "illegal"
                        record.winner = players[1 - pi].id
                        record.moves.append({"player": mover.id, "board": snap,
                                             "move": mv, "outcome": "illegal"})
                        return record

                    if pos[pi] in flames:
                        # 走入既有火焰:玩法性出局(reason=win)
                        record.reason = "win"
                        record.winner = players[1 - pi].id
                        record.moves.append({"player": mover.id,
                                             "board": self._snapshot(cells, bombs, flames, pos),
                                             "move": resulting, "outcome": "hit",
                                             "detail": "走入火焰"})
                        return record
                    record.moves.append({"player": mover.id,
                                         "board": self._snapshot(cells, bombs, flames, pos),
                                         "move": resulting, "outcome": "ok"})

                # 回合结算:引信推进 → 爆炸(旧火焰无论是否爆炸一并清除)
                for b in bombs:
                    b["fuse"] -= 1
                if any(b["fuse"] <= 0 for b in bombs):
                    flames = self._explode_phase(cells, bombs, radius)
                    snap = self._snapshot(cells, bombs, flames, pos)
                    deaths = [pi for pi in (0, 1) if pos[pi] in flames]
                    if deaths:
                        if len(deaths) == 2:
                            record.moves.append({
                                "player": players[0].id, "board": snap,
                                "move": pos[0], "outcome": "hit",
                                "detail": "爆炸同归于尽,平局"})
                            record.reason = "draw"
                        else:
                            record.reason = "win"
                            record.winner = players[1 - deaths[0]].id
                            record.moves.append({
                                "player": players[deaths[0]].id, "board": snap,
                                "move": pos[deaths[0]], "outcome": "hit",
                                "detail": "被爆炸波及"})
                        return record
                else:
                    flames = set()

            record.moves.append({"player": players[0].id,
                                 "board": self._snapshot(cells, bombs, flames, pos),
                                 "move": pos[0], "outcome": "ok",
                                 "detail": "回合数耗尽,平局"})
            record.reason = "draw"
            return record
        finally:
            for p in procs:
                await p.close()

    async def _play_multi(self, players: list[BotProgram], move_timeout: float,
                          fuse: int, radius: int, max_bombs: int,
                          max_rounds: int, rng_seed: str) -> GameRecord:
        """多人同局(3-4 人):全员进场,存活玩家按编号序轮流行动,死亡即离场。

        仅剩 1 人 → 胜;全灭 / 回合耗尽 → 平。名次组 = 存活组(并列)+ 死亡组按
        死亡顺序倒序(越早死越差),执行器据此走 apply_ranking 多人 ELO。
        """
        n = len(players)
        record = GameRecord(players=[b.id for b in players], first=players[0].id,
                            winner=None, reason="draw")
        rng = random.Random(rng_seed)
        cells = _layout(rng, SPAWNS[n])
        pos = [r * N + c for r, c in SPAWNS[n]]
        bombs: list[dict] = []
        flames: set[int] = set()
        alive = list(range(n))                       # 存活玩家下标(行动顺序)
        dead_groups: list[list[int]] = []            # 越早死名次越差;组内同期死亡并列
        procs: list[BotProcess] = []

        try:
            for bot in players:
                proc = BotProcess(bot, timeout=move_timeout)
                procs.append(proc)
                await proc.start()

            for _round in range(max_rounds):
                for pi in list(alive):
                    mover = players[pi]
                    me = pi + 1
                    snap = self._snapshot(cells, bombs, flames, pos)
                    try:
                        resp = await procs[pi].ask(
                            {"board": snap, "me": me, "config": {}})
                        mv = resp.get("move")
                    except ArenaError as e:
                        outcome = "timeout" if e.code == "BOT_TIMEOUT" else "crash"
                        record.moves.append({"player": mover.id, "board": snap,
                                             "outcome": outcome, "detail": e.message})
                        alive.remove(pi)
                        dead_groups.insert(0, [pi])
                        if len(alive) <= 1:
                            self._finish(record, players, alive, dead_groups)
                            return record
                        continue

                    resulting, err = self._apply_action(
                        cells, bombs, pos, pi, mv, fuse, max_bombs)
                    if err is not None:
                        record.moves.append({"player": mover.id, "board": snap,
                                             "move": mv, "outcome": "illegal"})
                        alive.remove(pi)
                        dead_groups.insert(0, [pi])
                        if len(alive) <= 1:
                            self._finish(record, players, alive, dead_groups)
                            return record
                        continue

                    if pos[pi] in flames:
                        # 走入既有火焰:玩法性出局
                        record.moves.append({"player": mover.id,
                                             "board": self._snapshot(cells, bombs, flames, pos),
                                             "move": resulting, "outcome": "hit",
                                             "detail": "走入火焰"})
                        alive.remove(pi)
                        dead_groups.insert(0, [pi])
                        if len(alive) <= 1:
                            self._finish(record, players, alive, dead_groups)
                            return record
                        continue
                    record.moves.append({"player": mover.id,
                                         "board": self._snapshot(cells, bombs, flames, pos),
                                         "move": resulting, "outcome": "ok"})

                # 回合结算:引信推进 → 爆炸(旧火焰无论是否爆炸一并清除)
                for b in bombs:
                    b["fuse"] -= 1
                if any(b["fuse"] <= 0 for b in bombs):
                    flames = self._explode_phase(cells, bombs, radius)
                    snap = self._snapshot(cells, bombs, flames, pos)
                    deaths = [pi for pi in alive if pos[pi] in flames]
                    if deaths:
                        for pi in deaths:
                            alive.remove(pi)
                        dead_groups.insert(0, deaths)
                        record.moves.append({
                            "player": players[deaths[0]].id, "board": snap,
                            "move": pos[deaths[0]], "outcome": "hit",
                            "detail": "被爆炸波及" if alive else "爆炸同归于尽,平局"})
                        if len(alive) <= 1:
                            self._finish(record, players, alive, dead_groups)
                            return record
                else:
                    flames = set()

            record.moves.append({"player": players[0].id,
                                 "board": self._snapshot(cells, bombs, flames, pos),
                                 "move": pos[0], "outcome": "ok",
                                 "detail": "回合数耗尽,平局"})
            self._finish(record, players, alive, dead_groups)
            return record
        finally:
            for p in procs:
                await p.close()
