# -*- coding: utf-8 -*-
"""测试公共设施:内存库 + 临时存储 + lifespan 接管的异步 client。"""
from __future__ import annotations

import httpx
import pytest

from app.core.config import Settings
from app.main import create_app


def make_settings(tmp_path, **overrides) -> Settings:
    defaults = dict(
        # 文件库(而非内存+StaticPool):worker 与轮询会话并发时需要真实事务隔离
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'nova.db'}",
        jwt_secret="test-secret",
        storage_dir=str(tmp_path / "storage"),
        cors_origins=[],
        admin_username="admin",
        admin_password="admin-password-1",
        llm_fallback_chain=["mock:mock"],
        max_concurrent_per_user=10,
        official_poll_seconds=0.05,
        eval_timeout_seconds=10.0,
        arena_move_timeout_seconds=3.0,
    )
    defaults.update(overrides)
    return Settings(_env_file=None, **defaults)  # 屏蔽开发者 .env,测试完全自包含


@pytest.fixture
def settings(tmp_path):
    return make_settings(tmp_path)


@pytest.fixture
async def app(settings):
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        yield app


@pytest.fixture
async def client(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def register_and_login(client, username="alice",
                             password="password-123", **extra):
    await client.post("/api/v2/auth/register",
                      json={"username": username, "password": password,
                            **extra})
    r = await client.post("/api/v2/auth/login",
                          json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def login_admin(client, settings):
    r = await client.post("/api/v2/auth/login",
                          json={"username": settings.admin_username,
                                "password": settings.admin_password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def seed_problem(client, admin_headers, key, *, ascend=True,
                       kind="optimization", contract=None):
    r = await client.put(f"/api/v2/admin/problems/{key}",
                         headers=admin_headers,
                         json={"name": key, "kind": kind, "ascend": ascend,
                               "contract": contract or {}})
    assert r.status_code == 200, r.text
    return r.json()


async def wait_run(client, headers, run_id, timeout=15.0, want="completed"):
    import asyncio

    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        r = await client.get(f"/api/v2/runs/{run_id}", headers=headers)
        assert r.status_code == 200, r.text
        status = r.json()["status"]
        if status in ("completed", "failed", "canceled"):
            return r.json()
        await asyncio.sleep(0.05)
    raise AssertionError(f"运行 {run_id} 超时未到终态(最后 {status})")
