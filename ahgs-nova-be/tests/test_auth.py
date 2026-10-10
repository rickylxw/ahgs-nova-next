# -*- coding: utf-8 -*-
"""健康检查 / 认证 / 限速。"""
from __future__ import annotations

import time

from .conftest import login_admin, register_and_login


async def test_health_ok(client):
    r = await client.get("/api/health")
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True
    assert "mode" not in d


async def test_meta_problem_kinds(client):
    r = await client.get("/api/v2/meta/problem-kinds")
    kinds = {k["key"] for k in r.json()["kinds"]}
    assert {"optimization", "game"} <= kinds


async def test_register_login_me(client):
    headers = await register_and_login(client, "alice")
    r = await client.get("/api/v2/auth/me", headers=headers)
    assert r.status_code == 200
    assert r.json()["username"] == "alice"
    assert r.json()["role"] == "user"


async def test_duplicate_register_conflict(client):
    body = {"username": "bob", "password": "password-123"}
    assert (await client.post("/api/v2/auth/register", json=body)).status_code == 201
    r = await client.post("/api/v2/auth/register", json=body)
    assert r.status_code == 409
    assert r.json()["code"] == "USERNAME_TAKEN"


async def test_structured_error_envelope(client):
    r = await client.get("/api/v2/runs/999",
                         headers=await register_and_login(client, "carol"))
    assert r.status_code == 404
    d = r.json()
    assert d["code"] == "NOT_FOUND"
    assert {"code", "message", "retryable", "detail"} <= set(d)


async def test_login_rate_limit_lockout(client, settings):
    """失败 5 次锁定(计划 §4.1:按账号+IP)。"""
    username = "dave"
    await register_and_login(client, username)
    for i in range(settings.login_max_failures):
        r = await client.post("/api/v2/auth/login",
                              json={"username": username, "password": "wrong-pass"})
        assert r.status_code == 401
    r = await client.post("/api/v2/auth/login",
                          json={"username": username, "password": "password-123"})
    # 正确密码也应被锁(防爆破)
    assert r.status_code == 423
    assert r.json()["code"] == "AUTH_LOCKED"


async def test_refresh_rotation(client):
    await register_and_login(client, "erin")
    r = await client.post("/api/v2/auth/login",
                          json={"username": "erin", "password": "password-123"})
    old = r.json()["refresh_token"]
    r2 = await client.post("/api/v2/auth/refresh", json={"refresh_token": old})
    assert r2.status_code == 200
    new = r2.json()["refresh_token"]
    assert new != old
    # 旧 refresh 一次性作废
    r3 = await client.post("/api/v2/auth/refresh", json={"refresh_token": old})
    assert r3.status_code == 401


async def test_expired_or_garbage_token_rejected(client):
    r = await client.get("/api/v2/auth/me",
                         headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 401
    assert r.json()["code"] == "AUTH_REQUIRED"


async def test_admin_created_and_rbac(client, settings):
    admin = await login_admin(client, settings)
    assert (await client.get("/api/v2/auth/me", headers=admin)).json()["role"] == "admin"
    user = await register_and_login(client, "frank")
    r = await client.post("/api/v2/admin/queue/pause", headers=user,
                          json={"paused": True})
    assert r.status_code == 403
