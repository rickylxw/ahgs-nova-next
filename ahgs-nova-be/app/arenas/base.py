# -*- coding: utf-8 -*-
"""Arena 扩展点基类(对战小游戏玩法)。

新增一款对战游戏三步走:
1. 写一个 Arena 子类,实现 key/display_name/bot_contract/run_match();
2. 注册:内置包内直接 ``registry.register(...)``,外部插件走
   NOVA_ARENA_PLUGINS 环境变量("模块:类" 逗号分隔);
3. 前端/脚本立刻可用 /api/v2/arena/* 全套端点(上传 bot、约战、ELO 榜)。

对局双方是用户上传的源码程序,由 arenas/runtime.py 在独立子进程里驱动,
按步超时即判负;生产部署换 Docker 沙箱池(计划 §3),Arena 实现本身不变。
"""
from __future__ import annotations

import itertools
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


@dataclass
class BotProgram:
    """参与对局的一份 bot 程序。"""
    id: int
    name: str
    code: str
    lang: str = "python"


@dataclass
class GameRecord:
    """一局的记录(referee 产出,原样进 Match.result)。

    双人局 players 恰 2 人;多人同局须填 ranking(名次组、最佳在前、组内并列),
    供执行器走多人 ELO 路径。
    """
    players: list[int]                     # bot id 顺序,与 first/turns 对应
    first: int                             # 先手 bot id
    winner: int | None                     # 胜者 bot id;平局 None
    reason: str                            # win|draw|illegal|timeout|crash
    moves: list[dict] = field(default_factory=list)
    ranking: list[list[int]] = field(default_factory=list)   # 多人局名次组;双人局留空

    def as_dict(self) -> dict:
        return {
            "players": self.players, "first": self.first,
            "winner": self.winner, "reason": self.reason, "moves": self.moves,
            "ranking": self.ranking,
        }


OnGameHook = Callable[[GameRecord], Awaitable[None]]


def apply_score_pair(scores: dict, record: GameRecord) -> None:
    """双人局通用记分:winner 为 None 记和,否则胜 +1 / 负 +1。"""
    a, b = record.players
    if record.winner is None:
        scores[a]["draw"] += 1
        scores[b]["draw"] += 1
    else:
        loser = b if record.winner == a else a
        scores[record.winner]["win"] += 1
        scores[loser]["loss"] += 1


class ArenaError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class Arena(ABC):
    """一款对战游戏的实现协议。"""

    key: str = "abstract"
    display_name: str = "Abstract Arena"
    bot_contract: str = ""                 # bot 源码入口约定(文档,展示给上传者)
    default_config: dict[str, Any] = {}
    min_bots: int = 2
    max_bots: int = 2
    # ---- 目录下发可选字段(前端回放渲染/文案协商用;见 ARENA_GAMES.md §8) ----
    board_shape: dict[str, int] | None = None   # {"rows": R, "cols": C},通用网格渲染
    pieces: dict[str, str] = {}                 # 棋子显示字符,如 {"1": "●", "2": "○"}
    cell_classes: dict[str, str] = {}           # 格子值 → CSS 类(缺省回退内置 1→x / 2→o)
    player_marks: dict[str, str] = {}           # 玩家编号(1 起) → 回放头部的棋子字符
    labels: dict[str, dict[str, str]] = {}      # {"reason": {...}, "outcome": {...}} 中文文案
    starter_code: str = ""                      # 可运行示例 bot(目录卡一键填入上传框)

    @abstractmethod
    async def run_match(self, bots: list[BotProgram], config: dict[str, Any],
                        on_game: OnGameHook | None = None) -> dict[str, Any]:
        """完整跑一场对阵,返回可 JSON 化的对局报告(写入 Match.result)。"""

    def merge_config(self, config: dict[str, Any] | None) -> dict[str, Any]:
        merged = dict(self.default_config)
        merged.update(config or {})
        return merged

    async def run_round_robin(
        self,
        bots: list[BotProgram],
        on_game: OnGameHook | None,
        play_one: Callable[[BotProgram, BotProgram], Awaitable[GameRecord]],
        games_per_pairing: int,
        report_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """双人游戏公共赛制(ARENA_GAMES.md §3.1):两两循环 × games_per_pairing,组内轮换先手。

        play_one(first, second) 跑一局并返回 GameRecord;记分与逐局 hook 在此统一处理。
        """
        scores = {b.id: {"win": 0, "loss": 0, "draw": 0} for b in bots}
        games: list[dict] = []
        for a, b in itertools.combinations(bots, 2):
            for game_no in range(games_per_pairing):
                first, second = (a, b) if game_no % 2 == 0 else (b, a)
                record = await play_one(first, second)
                games.append(record.as_dict())
                apply_score_pair(scores, record)
                if on_game is not None:
                    await on_game(record)
        return {
            "arena": self.key,
            "config": report_config or {},
            "games": games,
            "scores": scores,
        }
