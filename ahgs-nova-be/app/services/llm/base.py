# -*- coding: utf-8 -*-
"""LLM 网关(计划 §4.4)。

设计:
- 适配器协议 `LLMAdapter`:每家提供商一个实现;DeepSeek/Qwen/GLM/Kimi/OpenAI/本地
  vLLM 全部走 OpenAI 兼容适配器,Anthropic/Gemini 另写适配器即可接入。
- thinking 级别透传(GLM 语义:disabled/enabled;计划痛点 #3:推理模型不再被启动
  期连通性测试一票否决 —— 网关层短超时+一次重试)。
- 每次调用落 llm_calls 计量;失败按 fallback_chain 依序降级。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMRequest:
    messages: list[dict[str, str]]
    model: str = ""
    thinking: str = "default"      # default|disabled|low|high(网关统一级别)
    max_tokens: int = 4096
    temperature: float | None = None
    timeout: float = 60.0
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMResponse:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    provider: str = ""
    model: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


class LLMError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


class LLMAdapter:
    """提供商适配器协议。子类实现 chat();注册到 Gateway。"""

    name = "abstract"

    async def chat(self, req: LLMRequest) -> LLMResponse:  # pragma: no cover
        raise NotImplementedError

    @staticmethod
    def _latency_ms(start: float) -> int:
        return int((time.monotonic() - start) * 1000)
