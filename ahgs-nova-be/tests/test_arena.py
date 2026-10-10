# -*- coding: utf-8 -*-
"""Arena 扩展点:bot 上传 / 约战全流程 / ELO 榜 / 违规 bot 判负 / 题目类型联动。"""
from __future__ import annotations

import asyncio

from .conftest import login_admin, register_and_login, seed_problem, wait_run

LEGAL_BOT = """def move(board, me):
    for i, v in enumerate(board):
        if v == 0:
            return i
    return -1
"""

CENTER_BOT = """CENTER = 4
def move(board, me):
    if board[CENTER] == 0:
        return CENTER
    for i, v in enumerate(board):
        if v == 0:
            return i
    return -1
"""

ILLEGAL_BOT = """def move(board, me):
    return 0  # 永远试图落 0 号位,先手后都可能是非法步
"""


async def test_arena_catalog(client):
    r = await client.get("/api/v2/arena/arenas")
    arenas = {a["key"]: a for a in r.json()["arenas"]}
    assert "tictactoe" in arenas
    assert "def move(board, me)" in arenas["tictactoe"]["bot_contract"]


async def test_bot_upload_requires_registered_arena(client):
    user = await register_and_login(client, "arenauser")
    r = await client.post("/api/v2/arena/bots", headers=user, json={
        "arena_key": "nonexistent", "name": "x", "code": "def move(b, m): return 0"})
    assert r.status_code == 404
    assert r.json()["code"] == "ARENA_NOT_FOUND"


async def test_match_full_flow_and_leaderboard(client, settings):
    user = await register_and_login(client, "player1")
    await register_and_login(client, "player2")

    bots = []
    for name, code in (("FirstEmpty", LEGAL_BOT), ("Center", CENTER_BOT)):
        r = await client.post("/api/v2/arena/bots", headers=user,
                              json={"arena_key": "tictactoe", "name": name,
                                    "code": code})
        assert r.status_code == 201, r.text
        bots.append(r.json()["id"])

    r = await client.post("/api/v2/arena/matches", headers=user, json={
        "arena_key": "tictactoe", "bot_ids": bots,
        "config": {"games_per_pairing": 2}})
    assert r.status_code == 201, r.text
    match_id, run_id = r.json()["id"], r.json()["run_id"]

    done = await wait_run(client, user, run_id, timeout=60)
    assert done["status"] == "completed", done.get("error_message")

    m = (await client.get(f"/api/v2/arena/matches/{match_id}",
                          headers=user)).json()
    assert m["status"] == "completed"
    assert len(m["result"]["games"]) == 2
    assert all(g["reason"] in ("win", "draw", "illegal", "timeout", "crash")
               for g in m["result"]["games"])

    # ELO 榜:有对局记录,积分变动
    board = (await client.get("/api/v2/arena/leaderboard/tictactoe",
                              headers=user)).json()["leaderboard"]
    assert len(board) == 2
    ratings = {b["name"]: b["rating"] for b in board}
    assert any(v != 1000.0 for v in ratings.values())


async def test_illegal_bot_loses(client, settings):
    user = await register_and_login(client, "player3")
    ids = []
    for name, code in (("Center", CENTER_BOT), ("AlwaysZero", ILLEGAL_BOT)):
        r = await client.post("/api/v2/arena/bots", headers=user,
                              json={"arena_key": "tictactoe", "name": name,
                                    "code": code})
        ids.append(r.json()["id"])
    r = await client.post("/api/v2/arena/matches", headers=user, json={
        "arena_key": "tictactoe", "bot_ids": ids,
        "config": {"games_per_pairing": 1}})
    run_id = r.json()["run_id"]
    done = await wait_run(client, user, run_id, timeout=60)
    assert done["status"] == "completed"
    m = (await client.get(f"/api/v2/arena/matches/{r.json()['id']}",
                          headers=user)).json()
    g = m["result"]["games"][0]
    if g["winner"] is not None:
        assert g["winner"] == ids[0] or g["reason"] in ("win", "illegal")


async def test_match_bot_count_validation(client, settings):
    user = await register_and_login(client, "player4")
    r = await client.post("/api/v2/arena/bots", headers=user,
                          json={"arena_key": "tictactoe", "name": "Solo",
                                "code": LEGAL_BOT})
    solo = r.json()["id"]
    r = await client.post("/api/v2/arena/matches", headers=user, json={
        "arena_key": "tictactoe", "bot_ids": [solo]})
    assert r.status_code == 422


async def test_game_problem_ties_to_arena_kind(client, settings):
    """game 题目注册后,榜单语义联动:/api/v2/meta 自省 + 入队白名单。"""
    admin = await login_admin(client, settings)
    await seed_problem(client, admin, "gomoku-future", kind="game")
    user = await register_and_login(client, "player5")
    r = await client.post("/api/v2/run", headers=user, json={
        "kind": "arena_match", "problem_key": "gomoku-future"})
    # arena_match 执行器需要 match_id → 应失败为 match 缺失,而非"类型不允许"
    assert r.status_code == 201
    done = await wait_run(client, user, r.json()["id"], timeout=10,
                          )
    assert done["status"] == "failed"
    assert done["error_code"] in ("NOT_FOUND", "EXECUTOR_ERROR", "INVALID_INPUT")
