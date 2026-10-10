# -*- coding: utf-8 -*-
"""Mock 适配器:测试与无 LLM 环境的确定性应答。"""
from __future__ import annotations

import asyncio
import hashlib

from .base import LLMAdapter, LLMRequest, LLMResponse


class MockAdapter(LLMAdapter):
    name = "mock"

    def __init__(self, delay: float = 0.0):
        self.delay = delay

    async def chat(self, req: LLMRequest) -> LLMResponse:
        if self.delay:
            await asyncio.sleep(self.delay)
        seed = hashlib.sha256(repr(req.messages).encode()).hexdigest()[:8]
        text = (
            f"# mock reply ({seed})\n"
            f"# messages={len(req.messages)} thinking={req.thinking}\n"
            "def solve():\n    return None\n"
        )
        return LLMResponse(
            text=text,
            prompt_tokens=sum(len(m.get("content", "")) for m in req.messages) // 4,
            completion_tokens=len(text) // 4,
            provider=self.name, model=req.model,
        )
