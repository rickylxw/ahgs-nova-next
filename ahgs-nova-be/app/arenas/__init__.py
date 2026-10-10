# -*- coding: utf-8 -*-
"""Arena 注册表与外部插件加载。

外部插件示例(自定义一款对战游戏):
    # mypkg/mygame.py
    class MyGameArena(Arena):
        key = "mygame"; ...
环境变量 NOVA_ARENA_PLUGINS=mypkg.mygame:MyGameArena 即接入,
API/榜单/执行器零改动。内置游戏与新增规格见仓库根 ARENA_GAMES.md。
"""
from __future__ import annotations

import importlib
import logging

from .base import Arena, ArenaError, BotProgram, GameRecord  # noqa: F401
from .bomberman import BombermanArena
from .connect4 import Connect4Arena
from .gomoku import GomokuArena
from .reversi import ReversiArena
from .tron import TronArena
from .tictactoe import TicTacToeArena


class ArenaRegistry:
    def __init__(self) -> None:
        self._arenas: dict[str, Arena] = {}

    def register(self, arena: Arena) -> None:
        if arena.key in self._arenas:
            raise ValueError(f"Arena 重复注册: {arena.key}")
        self._arenas[arena.key] = arena

    def get(self, key: str) -> Arena:
        arena = self._arenas.get(key)
        if arena is None:
            raise ArenaError("ARENA_NOT_FOUND", f"未注册的对战游戏: {key}")
        return arena

    def has(self, key: str) -> bool:
        return key in self._arenas

    def list(self) -> list[dict]:
        return [
            {
                "key": a.key, "display_name": a.display_name,
                "bot_contract": a.bot_contract,
                "default_config": a.default_config,
                "min_bots": a.min_bots, "max_bots": a.max_bots,
                # 可选目录字段(前端回放渲染/文案协商;缺省为 None/空)
                "board_shape": a.board_shape,
                "pieces": a.pieces,
                "cell_classes": a.cell_classes,
                "player_marks": a.player_marks,
                "labels": a.labels,
                "starter_code": a.starter_code,
            }
            for a in self._arenas.values()
        ]

    def load_plugins(self, plugins: list[str]) -> list[str]:
        """plugins 形如 ["mypkg.mygame:MyGameArena", ...];返回成功加载项。"""
        loaded = []
        for spec in plugins or []:
            module_name, _, attr = spec.partition(":")
            try:
                module = importlib.import_module(module_name)
                obj = getattr(module, attr) if attr else None
                arena = obj() if isinstance(obj, type) else obj
                if not isinstance(arena, Arena):
                    raise TypeError(f"{spec} 不是 Arena 子类实例")
                self.register(arena)
                loaded.append(spec)
            except Exception as e:  # noqa: BLE001 — 插件失败不拖垮主进程
                logging.getLogger("nova.arena").warning(
                    "Arena 插件加载失败 %s: %s", spec, e)
        return loaded


# 默认注册表:内置六款对战游戏(井字棋为参考实现)
default_registry = ArenaRegistry()
default_registry.register(TicTacToeArena())
default_registry.register(Connect4Arena())
default_registry.register(GomokuArena())
default_registry.register(ReversiArena())
default_registry.register(TronArena())
default_registry.register(BombermanArena())
