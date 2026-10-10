# -*- coding: utf-8 -*-
"""OpenAI 兼容适配器:覆盖 DeepSeek/Qwen/GLM/Kimi/OpenAI/本地 vLLM 等。"""
from __future__ import annotations

import time

import httpx

from .base import LLMAdapter, LLMError, LLMRequest, LLMResponse

# thinking 统一级别 → OpenAI 兼容请求字段(GLM/智谱语义;其余提供商在 extra 里自行传)
_THINKING_MAP = {
    "disabled": {"type": "disabled"},
    "low": {"type": "enabled"},
    "high": {"type": "enabled"},
}


class OpenAICompatAdapter(LLMAdapter):
    name = "openai_compat"

    def __init__(self, base_url: str, api_key: str = "",
                 client: httpx.AsyncClient | None = None,
                 trust_env: bool = False,
                 name: str | None = None):
        # 命名注册(如 "ollama"):覆盖类默认名,网关按此名索引
        if name:
            self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        # trust_env=False:不受环境变量/Windows 系统代理影响 —— 本地 Ollama
        # (127.0.0.1)被系统代理劫持会直接超时;需要代理出海的提供商可显式传 True
        self._client = client or httpx.AsyncClient(timeout=None, trust_env=trust_env)

    async def chat(self, req: LLMRequest) -> LLMResponse:
        body: dict = {
            "model": req.model,
            "messages": req.messages,
            "max_tokens": req.max_tokens,
        }
        if req.temperature is not None:
            body["temperature"] = req.temperature
        if req.thinking in _THINKING_MAP:          # GLM 系透传
            body["thinking"] = _THINKING_MAP[req.thinking]
        body.update(req.extra)                     # 供应商特有字段覆盖入口

        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        start = time.monotonic()
        try:
            resp = await self._client.post(
                f"{self.base_url}/chat/completions", json=body, headers=headers,
                timeout=req.timeout,
            )
        except httpx.TimeoutException as e:
            raise LLMError("LLM_TIMEOUT", f"LLM 调用超时({req.timeout}s)", retryable=True) from e
        except httpx.HTTPError as e:
            raise LLMError("LLM_NETWORK", f"LLM 网络错误: {e}", retryable=True) from e

        latency = self._latency_ms(start)
        if resp.status_code == 429:
            raise LLMError("LLM_RATE_LIMITED", "LLM 限流", retryable=True)
        if resp.status_code >= 400:
            raise LLMError("LLM_HTTP_ERROR",
                           f"LLM 返回 {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        try:
            message = data["choices"][0]["message"]
            content = message.get("content") or ""
            # 思考类模型(Ollama + qwen3 等)可能把全部输出放进 reasoning 且 content
            # 为空(思考无法经参数关闭时)—— 此时退回 reasoning 供上层提取
            text = content if content.strip() else (message.get("reasoning") or "")
        except (KeyError, IndexError, TypeError) as e:
            raise LLMError("LLM_BAD_RESPONSE", f"LLM 应答结构异常: {e}") from e
        usage = data.get("usage") or {}
        return LLMResponse(
            text=text,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            latency_ms=latency,
            provider=self.name, model=req.model, raw=data,
        )
