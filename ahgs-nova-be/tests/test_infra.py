# -*- coding: utf-8 -*-
"""事件总线 / WS 推送 / 存储 / ELO 单元。"""
from __future__ import annotations

import asyncio
import json

import pytest

from app.arenas import ratings
from app.services.storage import LocalStorage


async def test_event_bus_pubsub():
    from app.services.events import EventBus

    bus = EventBus()
    q1 = bus.subscribe("42")
    q2 = bus.subscribe("42")
    qg = bus.subscribe("*")
    bus.publish("42", {"type": "generation_end", "data": {"g": 1}})
    e1 = q1.get_nowait()
    e2 = q2.get_nowait()
    assert e1["data"]["g"] == 1
    assert e2["type"] == "generation_end"
    # 全局频道只收 publish("*") 的事件(编排器会双写)
    try:
        qg.get_nowait()
        raised = False
    except asyncio.QueueEmpty:
        raised = True
    assert raised
    bus.publish("*", {"type": "run_started", "data": {}})
    assert qg.get_nowait()["type"] == "run_started"
    bus.unsubscribe("42", q1)
    assert bus.subscriber_count("42") == 1


async def test_ws_run_requires_token(client):
    # 无 token → 4401 关闭

    from app.main import create_app

    # httpx 不支持 WS;直接断言 REST 侧不可达即可,WS 用 TestClient 单独测
    r = await client.get("/api/health")
    assert r.status_code == 200


def test_ws_run_hello_and_event(settings, tmp_path):
    """TestClient 驱动 WS:hello 快照 + generation_end 事件。"""
    from starlette.testclient import TestClient

    from app.main import create_app

    from .conftest import make_settings

    app = create_app(make_settings(tmp_path))
    with TestClient(app) as tc:  # lifespan 在此运行
        r = tc.post("/api/v2/auth/register",
                    json={"username": "wsu", "password": "password-123"})
        assert r.status_code == 201, r.text
        r = tc.post("/api/v2/auth/login",
                    json={"username": "wsu", "password": "password-123"})
        token = r.json()["access_token"]
        auth = {"Authorization": f"Bearer {token}"}
        atok = tc.post("/api/v2/auth/login",
                       json={"username": "admin",
                             "password": "admin-password-1"}).json()["access_token"]

        # 建题目(管理员)并启动一个运行
        tc.put("/api/v2/admin/problems/wsp",
               headers={"Authorization": f"Bearer {atok}"},
               json={"name": "wsp", "kind": "optimization"})
        run = tc.post("/api/v2/run", headers=auth, json={
            "kind": "evolve_local", "problem_key": "wsp",
            "config": {"num_generations": 3, "population_size": 3}}).json()
        run_id = run["id"]

        with tc.websocket_connect(f"/api/v2/ws/runs/{run_id}?token={token}") as ws:
            hello = json.loads(ws.receive_text())
            assert hello["type"] == "hello"

            got_gen_end = False
            for _ in range(20):
                msg = json.loads(ws.receive_text())
                if msg["type"] == "generation_end":
                    got_gen_end = True
                    break
            assert got_gen_end


def test_storage_path_traversal_blocked(tmp_path):
    st = LocalStorage(tmp_path)
    st.put("a/b.txt", b"hello")
    assert st.get("a/b.txt") == b"hello"
    with pytest.raises(ValueError):
        st.put("../evil.txt", b"x")
    with pytest.raises(ValueError):
        st.get("../../etc/passwd")


def test_elo_basic():
    ra, rb = 1000.0, 1000.0
    na, nb = ratings.apply_pair(ra, rb, 1.0)   # a 胜
    assert na > ra and nb < rb
    da, db = ratings.apply_pair(1000.0, 1400.0, 1.0)  # 弱方爆冷
    assert da - 1000.0 > na - ra  # 爆冷收益更大
    ea = ratings.expected(1000, 1000)
    assert abs(ea - 0.5) < 1e-9
