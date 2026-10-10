# -*- coding: utf-8 -*-
"""进程内事件总线:WebSocket 推送的数据源(计划痛点 #10:替代 45s 轮询)。

key 为订阅主题:run_id 字符串 = 单运行频道;``*`` = 全局频道。
多实例部署时可换 Redis pub/sub 后端,发布接口不变。
"""
from __future__ import annotations

import asyncio
from typing import Any

MAX_QUEUE = 512


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue]] = {}

    def subscribe(self, key: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=MAX_QUEUE)
        self._subs.setdefault(key, set()).add(q)
        return q

    def unsubscribe(self, key: str, q: asyncio.Queue) -> None:
        subs = self._subs.get(key)
        if subs:
            subs.discard(q)
            if not subs:
                self._subs.pop(key, None)

    def publish(self, key: str, event: dict[str, Any]) -> None:
        """非阻塞投递;订阅端满载时丢弃(监控场景可容忍)。"""
        for q in list(self._subs.get(key, ())):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def subscriber_count(self, key: str) -> int:
        return len(self._subs.get(key, ()))
