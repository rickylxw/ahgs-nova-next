# -*- coding: utf-8 -*-
"""网关:适配器注册、降级链、调用计量。"""
from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from ...core.security import now_utc
from ...db.models import LlmCall
from .base import LLMAdapter, LLMError, LLMRequest, LLMResponse
from .mock import MockAdapter
from .openai_compat import OpenAICompatAdapter

log = logging.getLogger("nova.llm")


class LLMGateway:
    def __init__(self) -> None:
        self._adapters: dict[str, LLMAdapter] = {}
        self.fallback_chain: list[tuple[str, str]] = []   # [(adapter_name, model)]
        self._register_default_adapters()

    # ---- 适配器管理 ----

    def _register_default_adapters(self) -> None:
        self.register_adapter(MockAdapter())

    def register_adapter(self, adapter: LLMAdapter) -> None:
        self._adapters[adapter.name] = adapter

    def configure_openai_compat(self, name: str, base_url: str, api_key: str = "") -> None:
        """注册/更新一个 OpenAI 兼容提供商(平台默认 key 池或命名池)。"""
        self.register_adapter(OpenAICompatAdapter(base_url, api_key, name=name))

    def set_fallback_chain(self, chain: list[str]) -> None:
        """chain 形如 ["openai_compat:glm-4.5-air", "mock:mock"]。"""
        parsed = []
        for item in chain:
            adapter, _, model = item.partition(":")
            if adapter in self._adapters:
                parsed.append((adapter, model or "default"))
        self.fallback_chain = parsed or [("mock", "mock")]

    def list_providers(self) -> list[dict]:
        return [
            {"name": name, "class": type(a).__name__}
            for name, a in self._adapters.items()
        ]

    # ---- 调用 ----

    async def chat(self, req: LLMRequest, *, run_id: int | None = None,
                   user_id: int | None = None, db: AsyncSession | None = None,
                   chain: list[tuple[str, str]] | None = None) -> LLMResponse:
        """按降级链依序尝试;每次尝试(含失败)都落 llm_calls。"""
        attempts = chain if chain is not None else (self.fallback_chain or [("mock", "mock")])
        last_err: LLMError | None = None
        for adapter_name, model in attempts:
            adapter = self._adapters.get(adapter_name)
            if adapter is None:
                continue
            req.model = model
            try:
                resp = await adapter.chat(req)
                await self._log(db, run_id, user_id, adapter_name, req, resp, None)
                return resp
            except LLMError as e:
                last_err = e
                await self._log(db, run_id, user_id, adapter_name, req, None, e)
                if not e.retryable:
                    raise
                log.warning("LLM 降级: %s:%s -> %s", adapter_name, model, e.code)
        raise last_err or LLMError("LLM_NO_PROVIDER", "无可用的 LLM 提供商")

    async def _log(self, db, run_id, user_id, provider, req: LLMRequest,
                   resp: LLMResponse | None, err: LLMError | None) -> None:
        if db is None:
            return
        db.add(LlmCall(
            run_id=run_id, user_id=user_id, provider=provider, model=req.model,
            thinking=req.thinking,
            prompt_tokens=resp.prompt_tokens if resp else 0,
            completion_tokens=resp.completion_tokens if resp else 0,
            latency_ms=resp.latency_ms if resp else 0,
            ok=resp is not None, error_code=err.code if err else None,
            created_at=now_utc(),
        ))
