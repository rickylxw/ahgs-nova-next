# -*- coding: utf-8 -*-
"""队列后端抽象(计划 §3:Redis+ARQ 起步可选,进程内优先跑通)。

新增后端只需实现 QueueBackend 协议;编排器不感知实现。
"""
from __future__ import annotations

import itertools
import asyncio
from dataclasses import dataclass


@dataclass(order=True)
class _Item:
    priority: int
    seq: int
    run_id: int


class QueueBackend:
    async def enqueue(self, run_id: int, priority: int = 0) -> None:  # pragma: no cover
        raise NotImplementedError

    async def dequeue(self) -> int:  # pragma: no cover
        raise NotImplementedError

    @property
    def depth(self) -> int:  # pragma: no cover
        raise NotImplementedError


class MemoryQueue(QueueBackend):
    """进程内优先级队列(先入先出 tie-break)。"""

    def __init__(self) -> None:
        self._q: asyncio.PriorityQueue[_Item] = asyncio.PriorityQueue()
        self._seq = itertools.count()

    async def enqueue(self, run_id: int, priority: int = 0) -> None:
        self._q.put_nowait(_Item(priority, next(self._seq), run_id))

    async def dequeue(self) -> int:
        return (await self._q.get()).run_id

    @property
    def depth(self) -> int:
        return self._q.qsize()
