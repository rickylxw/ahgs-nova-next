# -*- coding: utf-8 -*-
"""LLM 网关:降级链 / 调用计量 / thinking 透传;预筛端点结构化失败原因。"""
from __future__ import annotations

from app.services.llm import (
    LLMAdapter, LLMError, LLMRequest, MockAdapter, OpenAICompatAdapter,
)
from app.services.evaluators import evaluate_candidate

from .conftest import login_admin, register_and_login


class FlakyAdapter(LLMAdapter):
    name = "flaky"

    def __init__(self, fail_times: int = 2):
        self.fail_times = fail_times
        self.calls = 0

    async def chat(self, req: LLMRequest):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise LLMError("LLM_RATE_LIMITED", "限流", retryable=True)
        return await MockAdapter().chat(req)


async def test_gateway_fallback_chain_and_logging(app, client):
    ctx = app.state.ctx
    flaky = FlakyAdapter(fail_times=2)
    ctx.llm.register_adapter(flaky)
    ctx.llm.set_fallback_chain(["flaky:qwen", "mock:mock"])

    from app.db.session import make_session_factory
    session_factory = ctx.session_factory
    async with session_factory() as db:
        resp = await ctx.llm.chat(
            LLMRequest(messages=[{"role": "user", "content": "hi"}],
                       model="qwen"),
            db=db,
        )
        await db.commit()
    assert resp.provider == "mock"          # 第一次失败即降级到 mock
    assert flaky.calls == 1

    admin_headers = None
    rows = None
    # llm_calls 已计量
    user = await register_and_login(client, "llmuser")
    admin_headers = user  # 非管理员看不了 calls,这里直接查库
    from sqlalchemy import select
    from app.db.models import LlmCall
    async with session_factory() as db:
        rows = (await db.scalars(select(LlmCall))).all()
    assert len(rows) == 2
    assert [r.ok for r in rows] == [False, True]


async def test_openai_compat_thinking_passthrough(app):
    import httpx

    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.read()
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2},
        })

    adapter = OpenAICompatAdapter(
        "https://llm.test/api", api_key="k",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    resp = await adapter.chat(LLMRequest(
        messages=[{"role": "user", "content": "hi"}], model="glm-5.3-flash",
        thinking="disabled"))
    assert resp.text == "ok"
    import json
    body = json.loads(captured["body"])
    assert body["thinking"] == {"type": "disabled"}  # GLM 语义透传
    assert body["model"] == "glm-5.3-flash"


async def test_gateway_non_retryable_no_fallback(app):
    ctx = app.state.ctx
    boom = FlakyAdapter(fail_times=0)

    class HardFail(LLMAdapter):
        name = "hard"

        async def chat(self, req):
            raise LLMError("LLM_HTTP_ERROR", "参数错误", retryable=False)

    mock = MockAdapter()
    ctx.llm.register_adapter(HardFail())
    ctx.llm.register_adapter(boom)
    ctx.llm.set_fallback_chain(["hard:x", "mock:mock"])
    import pytest as _pytest
    from app.services.llm import LLMError as _LE
    with _pytest.raises(_LE) as ei:
        await ctx.llm.chat(LLMRequest(messages=[], model="x"))
    assert ei.value.code == "LLM_HTTP_ERROR"
    del boom, mock


async def test_prescreen_structured_outcomes(client, settings):
    admin = await login_admin(client, settings)
    user = await register_and_login(client, "pre")
    await client.put("/api/v2/admin/problems/pres", headers=admin,
                     json={"name": "pres", "kind": "optimization"})

    good = "def evaluate(instance, config):\n    return 42\n"
    r = await client.post("/api/v2/prescreen", headers=user, json={
        "problem_key": "pres", "candidate_code": good, "timeout_seconds": 5})
    d = r.json()
    assert d["ok"] is True and d["objective"] == 42.0 and d["fail_reason"] is None

    bad = "def evaluate(instance, config):\n    raise ValueError('boom')\n"
    d2 = (await client.post("/api/v2/prescreen", headers=user, json={
        "problem_key": "pres", "candidate_code": bad,
        "timeout_seconds": 5})).json()
    assert d2["ok"] is False and d2["fail_reason"] == "crash"

    syntax_err = "def evaluate(:\n    pass\n"
    d3 = (await client.post("/api/v2/prescreen", headers=user, json={
        "problem_key": "pres", "candidate_code": syntax_err,
        "timeout_seconds": 5})).json()
    assert d3["ok"] is False and d3["fail_reason"] == "load_error"

    loop = "def evaluate(instance, config):\n    import time\n" \
           "    time.sleep(30)\n    return 1\n"
    d4 = (await client.post("/api/v2/prescreen", headers=user, json={
        "problem_key": "pres", "candidate_code": loop,
        "timeout_seconds": 2})).json()
    assert d4["ok"] is False and d4["fail_reason"] == "timeout"


async def test_evaluate_candidate_direct():
    out = await evaluate_candidate(
        "def evaluate(i, c):\n    return {'objective': -3.5}\n",
        instance={"x": 1})
    assert out.ok and out.objective == -3.5


async def test_admin_llm_chat_provider_pin(client, settings):
    """回归:指定 provider 时 chain 引用未定义变量 p 导致 500。"""
    admin = await login_admin(client, settings)
    r = await client.post("/api/v2/admin/llm/chat", headers=admin, json={
        "messages": [{"role": "user", "content": "hi"}],
        "provider": "mock", "model": "demo-model"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["provider"] == "mock"
    assert d["model"] == "demo-model"


async def test_admin_llm_chat_unknown_provider(client, settings):
    admin = await login_admin(client, settings)
    r = await client.post("/api/v2/admin/llm/chat", headers=admin, json={
        "messages": [], "provider": "no-such-provider"})
    assert r.status_code == 502
    assert r.json()["code"] == "LLM_NO_PROVIDER"


async def test_admin_llm_chat_default_chain(client, settings):
    admin = await login_admin(client, settings)
    r = await client.post("/api/v2/admin/llm/chat", headers=admin, json={
        "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 200, r.text
    assert r.json()["provider"] == "mock"
