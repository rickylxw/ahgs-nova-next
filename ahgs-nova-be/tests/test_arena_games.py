# -*- coding: utf-8 -*-
"""对战游戏:裁判规则单测 + 约战全流程冒烟(P0 + P1)。

确定性基准(首个合法步 bot 互弈,见 ARENA_GAMES.md §5/§6):
- gomoku:先手第 61 步沿反对角连五获胜;
- reversi:60 步后双方无着,自动 pass ×2,终局 19:45 后手白胜;
- tron:首个安全方向 bot 互弈,先手第 59 步撞墙出局(58 步移动 + 1 步 hit),后手胜;
- bomberman(seed=12345):首个合法行动 bot 互弈,100 回合耗尽 200 步平局。
"""
from __future__ import annotations

import random

import pytest

from app.arenas import default_registry
from app.arenas.base import GameRecord, apply_score_pair
from app.arenas.bomberman import SPAWNS, BombermanArena, _layout
from app.arenas.connect4 import WIN_LINES, COLS, ROWS, Connect4Arena
from app.arenas.gomoku import SIZE, GomokuArena
from app.arenas.ratings import apply_pair, apply_ranking
from app.arenas.reversi import ReversiArena

from .conftest import register_and_login, wait_run

FIRST_COL_BOT = """def move(board, me):
    for col in range(7):
        if board[col] == 0:
            return col
    return -1
"""

RANDOM_COL_BOT = """import random

def move(board, me):
    cols = [c for c in range(7) if board[c] == 0]
    return random.choice(cols) if cols else -1
"""

OFF_BOARD_BOT = """def move(board, me):
    return 42  # 永远越界
"""

FIRST_EMPTY_GOMOKU = """def move(board, me):
    for i, v in enumerate(board):
        if v == 0:
            return i
    return -1
"""

FIRST_LEGAL_REVERSI = """def move(board, me):
    opp, n = 3 - me, 8
    for idx in range(64):
        if board[idx] != 0:
            continue
        r, c = divmod(idx, n)
        for dr, dc in ((0,1),(0,-1),(1,0),(-1,0),(1,1),(1,-1),(-1,1),(-1,-1)):
            i, j, k = r + dr, c + dc, 0
            while 0 <= i < n and 0 <= j < n and board[i*n+j] == opp:
                i += dr; j += dc; k += 1
            if k and 0 <= i < n and 0 <= j < n and board[i*n+j] == me:
                return idx
    return -1
"""

OCCUPIED_REVERSI = """def move(board, me):
    return 27  # 开局即被占用
"""

TRON_FIRST_SAFE = """DELTAS = ((-1, 0), (1, 0), (0, -1), (0, 1))
N = 15

def move(board, me):
    head = board.index(me + 2)
    r, c = divmod(head, N)
    for d, (dr, dc) in enumerate(DELTAS):
        rr, cc = r + dr, c + dc
        if 0 <= rr < N and 0 <= cc < N and board[rr * N + cc] == 0:
            return d
    return 0
"""

BOMBER_FIRST_ACTION = """DELTAS = ((-1, 0), (1, 0), (0, -1), (0, 1))
N = 13

def move(board, me):
    cells = board["cells"]
    r, c = divmod(board["players"][me - 1], N)
    opp = board["players"][2 - me]
    for d, (dr, dc) in enumerate(DELTAS):
        rr, cc = r + dr, c + dc
        if 0 <= rr < N and 0 <= cc < N:
            i = rr * N + cc
            if i != opp and cells[i] in (0, 4):
                return d
    if not any(b["cell"] == r * N + c for b in board["bombs"]):
        return 4
    return 5
"""

ALWAYS_PLANT = """def move(board, me):
    return 4
"""

ALWAYS_PASS = """def move(board, me):
    return 5
"""


# ---- 目录字段 ----

async def test_games_catalog_fields(client):
    r = await client.get("/api/v2/arena/arenas")
    arenas = {a["key"]: a for a in r.json()["arenas"]}
    for key in ("tictactoe", "connect4", "gomoku", "reversi", "tron", "bomberman"):
        assert key in arenas, key
    assert arenas["tictactoe"]["board_shape"] == {"rows": 3, "cols": 3}
    assert arenas["connect4"]["board_shape"] == {"rows": 6, "cols": 7}
    assert arenas["gomoku"]["board_shape"] == {"rows": 15, "cols": 15}
    assert arenas["reversi"]["board_shape"] == {"rows": 8, "cols": 8}
    assert arenas["tron"]["board_shape"] == {"rows": 15, "cols": 15}
    assert arenas["bomberman"]["board_shape"] == {"rows": 13, "cols": 13}
    for key in ("tictactoe", "connect4", "gomoku", "reversi", "tron", "bomberman"):
        a = arenas[key]
        assert a["pieces"], key
        assert a["player_marks"], key
        assert "win" in a["labels"]["reason"], key
        assert a["starter_code"].startswith(("import", "def")), key
    assert "pass" in arenas["reversi"]["labels"]["outcome"]
    assert "hit" in arenas["tron"]["labels"]["outcome"]
    assert arenas["bomberman"]["cell_classes"]["4"] == "flame"
    assert arenas["bomberman"]["max_bots"] == 4


# ---- 裁判规则单测(不涉及子进程) ----

def test_connect4_lines_and_drop():
    assert len(WIN_LINES) == 69
    board = [0] * (ROWS * COLS)
    assert Connect4Arena._drop(board, 0) == 5 * COLS        # 最底行
    board[5 * COLS] = 1
    assert Connect4Arena._drop(board, 0) == 4 * COLS
    for r in range(ROWS):                                    # 填满该列
        board[r * COLS] = 1
    assert Connect4Arena._drop(board, 0) is None


def test_connect4_has_won():
    board = [0] * (ROWS * COLS)
    for c in range(4):                                       # 横四连
        board[5 * COLS + c] = 1
    assert Connect4Arena._has_won(board, 1)
    board = [0] * (ROWS * COLS)
    for i in range(4):                                       # 主斜四连
        board[(1 + i) * COLS + i] = 2
    assert Connect4Arena._has_won(board, 2)
    board = [0] * (ROWS * COLS)
    board[5 * COLS] = board[5 * COLS + 1] = board[5 * COLS + 2] = 1
    assert not Connect4Arena._has_won(board, 1)              # 三连不算


def test_gomoku_has_won():
    board = [0] * (SIZE * SIZE)
    for c in range(5):                                       # 横五
        board[7 * SIZE + c] = 1
    assert GomokuArena._has_won(board, 7 * SIZE + 4, 1)
    board = [0] * (SIZE * SIZE)
    for c in range(4):                                       # 四子被两头堵
        board[7 * SIZE + 3 + c] = 1
    board[7 * SIZE + 2] = 2
    board[7 * SIZE + 7] = 2
    assert not GomokuArena._has_won(board, 7 * SIZE + 6, 1)
    board = [0] * (SIZE * SIZE)                              # 长连六子亦胜
    for c in range(6):
        board[7 * SIZE + c] = 2
    assert GomokuArena._has_won(board, 7 * SIZE + 5, 2)
    board = [0] * (SIZE * SIZE)                              # 反斜五连
    for i in range(5):
        board[(5 + i) * SIZE + 9 - i] = 1
    assert GomokuArena._has_won(board, 9 * SIZE + 5, 1)


def test_reversi_rules():
    board = [0] * 64
    board[27], board[36] = 2, 2
    board[28], board[35] = 1, 1
    # 标准开局黑方合法点:d3/c4/f5/e6
    legal = ReversiArena._legal_moves(board, 1)
    assert set(legal) == {19, 26, 37, 44}
    assert ReversiArena._flips_for(board, 19, 1) == [27]

    record = GameRecord(players=[11, 22], first=11, winner=None, reason="draw")
    ReversiArena._settle_by_count(record, [1] * 40 + [2] * 24)
    assert record.reason == "win" and record.winner == 11
    record = GameRecord(players=[11, 22], first=11, winner=None, reason="draw")
    ReversiArena._settle_by_count(record, [1] * 20 + [2] * 20 + [0] * 24)
    assert record.reason == "draw" and record.winner is None


def test_apply_score_pair():
    scores = {1: {"win": 0, "loss": 0, "draw": 0}, 2: {"win": 0, "loss": 0, "draw": 0}}
    apply_score_pair(scores, GameRecord([1, 2], 1, 1, "win"))
    apply_score_pair(scores, GameRecord([1, 2], 2, None, "draw"))
    assert scores == {1: {"win": 1, "loss": 0, "draw": 1},
                      2: {"win": 0, "loss": 1, "draw": 1}}


# ---- 约战全流程(真实子进程) ----

async def _upload(client, headers, arena_key, name, code):
    r = await client.post("/api/v2/arena/bots", headers=headers,
                          json={"arena_key": arena_key, "name": name, "code": code})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _run_match(client, headers, arena_key, bot_ids, config):
    r = await client.post("/api/v2/arena/matches", headers=headers,
                          json={"arena_key": arena_key, "bot_ids": bot_ids,
                                "config": config})
    assert r.status_code == 201, r.text
    done = await wait_run(client, headers, r.json()["run_id"], timeout=120)
    assert done["status"] == "completed", done.get("error_message")
    m = await client.get(f"/api/v2/arena/matches/{r.json()['id']}", headers=headers)
    return m.json()


async def test_connect4_match_flow(client):
    user = await register_and_login(client, "c4player")
    bots = [await _upload(client, user, "connect4", "Random", RANDOM_COL_BOT),
            await _upload(client, user, "connect4", "FirstCol", FIRST_COL_BOT)]
    m = await _run_match(client, user, "connect4", bots, {"games_per_pairing": 2})
    games = m["result"]["games"]
    assert len(games) == 2
    assert [g["first"] for g in games] == bots               # 轮换先手
    for g in games:
        assert g["reason"] in ("win", "draw")
        assert g["winner"] is None if g["reason"] == "draw" else g["winner"] in bots
        assert all(mv["board"] and len(mv["board"]) == 42 for mv in g["moves"])
    scores = m["result"]["scores"]
    assert {int(k) for k in scores} == set(bots)
    for s in scores.values():
        assert s["win"] + s["loss"] + s["draw"] == 2
    board = (await client.get("/api/v2/arena/leaderboard/connect4",
                              headers=user)).json()["leaderboard"]
    assert {b["id"] for b in board} == set(bots)


async def test_connect4_off_board_bot_loses(client):
    user = await register_and_login(client, "c4bad")
    bots = [await _upload(client, user, "connect4", "Off", OFF_BOARD_BOT),
            await _upload(client, user, "connect4", "FirstCol", FIRST_COL_BOT)]
    m = await _run_match(client, user, "connect4", bots, {"games_per_pairing": 2})
    assert all(g["reason"] == "illegal" and g["winner"] == bots[1]
               for g in m["result"]["games"])


async def test_gomoku_first_empty_duel(client):
    user = await register_and_login(client, "gplayer")
    bots = [await _upload(client, user, "gomoku", "A", FIRST_EMPTY_GOMOKU),
            await _upload(client, user, "gomoku", "B", FIRST_EMPTY_GOMOKU)]
    m = await _run_match(client, user, "gomoku", bots, {"games_per_pairing": 1})
    g = m["result"]["games"][0]
    assert g["reason"] == "win" and g["winner"] == bots[0]
    assert len(g["moves"]) == 61                             # 先手第 61 步反对角连五


async def test_reversi_first_legal_duel(client):
    user = await register_and_login(client, "rplayer")
    bots = [await _upload(client, user, "reversi", "A", FIRST_LEGAL_REVERSI),
            await _upload(client, user, "reversi", "B", FIRST_LEGAL_REVERSI)]
    m = await _run_match(client, user, "reversi", bots, {"games_per_pairing": 1})
    g = m["result"]["games"][0]
    assert g["reason"] == "win" and g["winner"] == bots[1]   # 后手白 19:45 计子胜
    assert [mv["outcome"] for mv in g["moves"][-2:]] == ["pass", "pass"]
    assert g["moves"][-1]["detail"] == "19:45 子数比"
    assert any(mv["board"] and len(mv["board"]) == 64 for mv in g["moves"])


async def test_reversi_occupied_bot_loses(client):
    user = await register_and_login(client, "rbad")
    bots = [await _upload(client, user, "reversi", "Occ", OCCUPIED_REVERSI),
            await _upload(client, user, "reversi", "First", FIRST_LEGAL_REVERSI)]
    m = await _run_match(client, user, "reversi", bots, {"games_per_pairing": 2})
    assert all(g["reason"] == "illegal" and g["winner"] == bots[1]
               for g in m["result"]["games"])


async def test_match_rejects_over_max_bots(client):
    user = await register_and_login(client, "c4max")
    ids = [await _upload(client, user, "connect4", f"b{i}", FIRST_COL_BOT)
           for i in range(3)]
    r = await client.post("/api/v2/arena/matches", headers=user,
                          json={"arena_key": "connect4", "bot_ids": ids})
    assert r.status_code == 422
    assert "最多允许" in r.json()["message"]


def test_registry_has_no_duplicate_keys():
    keys = [a["key"] for a in default_registry.list()]
    assert len(keys) == len(set(keys))


# ---- P1:炸弹人规则单测 ----

def _walls() -> list[int]:
    """边框全硬墙的空场地。"""
    cells = [0] * 169
    for i in range(13):
        cells[i] = cells[12 * 13 + i] = 1
        cells[i * 13] = cells[i * 13 + 12] = 1
    return cells


def test_bomberman_layout_deterministic():
    a = _layout(random.Random("s1"), SPAWNS[2])
    b = _layout(random.Random("s1"), SPAWNS[2])
    c = _layout(random.Random("s2"), SPAWNS[2])
    assert a == b and a != c
    assert a[0] == 1 and a[2 * 13 + 2] == 1          # 边框/柱状硬墙
    assert a[1 * 13 + 1] == 0 and a[11 * 13 + 11] == 0   # 出生点清空
    assert sum(1 for v in a if v == 2) > 20          # 软墙已填充


def test_bomberman_spawns_by_player_count():
    for n, spots in SPAWNS.items():
        cells = _layout(random.Random("x"), spots)
        idxs = [r * 13 + c for r, c in spots]
        assert len(set(idxs)) == n
        assert all(cells[i] == 0 for i in idxs)
        for i in idxs:                               # 出生点周围(非结构格)清空
            r, c = divmod(i, 13)
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                rr, cc = r + dr, c + dc
                if 0 < rr < 12 and 0 < cc < 12 and not (rr % 2 == 0 and cc % 2 == 0):
                    assert cells[rr * 13 + cc] == 0, (n, rr, cc)


def test_bomberman_cells_are_exclusive():
    """任何两名玩家不可占据同一格(2-4 人一律适用)。"""
    arena = BombermanArena()
    cells = [0] * 169
    pos = [14, 15, 27, 40]                           # (1,1) (1,2) (2,1) (3,1)
    _, err = arena._apply_action(cells, [], pos, 0, 3, 3, 2)   # 1 号向右撞 2 号
    assert err == "occupied_by_player"
    _, err = arena._apply_action(cells, [], pos, 2, 0, 3, 2)   # 3 号向上撞 1 号
    assert err == "occupied_by_player"
    _, err = arena._apply_action(cells, [], pos[:2], 0, 3, 3, 2)  # 双人局同样生效
    assert err == "occupied_by_player"
    _, err = arena._apply_action(cells, [], pos[:2], 1, 1, 3, 2)  # 2 号向下无冲突可行
    assert err is None


def test_apply_ranking_matches_pair_and_zero_sum():
    # n=2 与 apply_pair 完全一致(胜/负/平,平局用并列组表达)
    for score_a, ranking in ((1.0, [[11], [22]]), (0.0, [[22], [11]]),
                             (0.5, [[11, 22]])):
        ra, rb = apply_pair(1000.0, 1200.0, score_a)
        m = {11: 1000.0, 22: 1200.0}
        apply_ranking(m, ranking)
        assert m[11] == pytest.approx(ra) and m[22] == pytest.approx(rb)

    # 多人:严格零和 + 名次方向正确
    m = {1: 1000.0, 2: 1100.0, 3: 900.0, 4: 1050.0}
    before = sum(m.values())
    apply_ranking(m, [[2], [1, 4], [3]])             # 2 冠军,1/4 并列次名,3 末位
    assert sum(m.values()) == pytest.approx(before)
    assert m[2] > 1100.0 and m[3] < 900.0


def test_bomberman_blast_rules():
    # 硬墙截断火舌:中心 (1,1),上/左撞边框,右/下走满半径
    flames, destroyed, chain = BombermanArena._blast(_walls(), set(), 14, 2)
    assert flames == {14, 15, 16, 27, 40} and destroyed == [] and chain == []
    # 软墙:炸毁并截断
    cells = _walls()
    cells[16] = 2                                    # (1,3) 软墙
    flames, destroyed, _ = BombermanArena._blast(cells, set(), 14, 2)
    assert flames == {14, 15, 16, 27, 40} and destroyed == [16]
    # 连锁引爆:火舌碰到炸弹格即触发并截断该方向
    flames, _, chain = BombermanArena._blast(_walls(), {15, 16}, 14, 2)
    assert chain == [15] and 15 in flames and 16 not in flames


def test_bomberman_explode_phase_chain_and_cleanup():
    cells = _walls()
    bombs = [{"cell": 15, "fuse": 0, "owner": 1},
             {"cell": 16, "fuse": 3, "owner": 2}]
    flames = BombermanArena()._explode_phase(cells, bombs, 2)
    assert all(b["cell"] not in (15, 16) for b in bombs)   # 两颗都被引爆移除
    assert {14, 15, 16, 17, 18} <= flames                  # 16 被连锁引爆


async def test_bomberman_first_action_duel_exhausts_rounds(client):
    user = await register_and_login(client, "bmplayer")
    bots = [await _upload(client, user, "bomberman", "A", BOMBER_FIRST_ACTION),
            await _upload(client, user, "bomberman", "B", BOMBER_FIRST_ACTION)]
    m = await _run_match(client, user, "bomberman", bots,
                         {"games_per_pairing": 1, "seed": 12345})
    assert m["result"]["config"]["seed"] == 12345    # seed 写回可复现
    g = m["result"]["games"][0]
    assert g["reason"] == "draw" and g["winner"] is None
    assert len(g["moves"]) == 201                    # 100 回合 × 双方 + 回合耗尽收尾
    assert g["moves"][-1]["detail"] == "回合数耗尽,平局"
    assert any(mv["board"].get("bombs") is not None for mv in g["moves"])


async def test_bomberman_suicide_bomb_with_fast_fuse(client):
    """fuse=1:先手布雷后原地不动,回合结算被自己的炸弹送走。"""
    user = await register_and_login(client, "bmboom")
    bots = [await _upload(client, user, "bomberman", "Planter", ALWAYS_PLANT),
            await _upload(client, user, "bomberman", "Passer", ALWAYS_PASS)]
    m = await _run_match(client, user, "bomberman", bots,
                         {"games_per_pairing": 1, "fuse": 1})
    g = m["result"]["games"][0]
    assert g["reason"] == "win" and g["winner"] == bots[1]
    assert len(g["moves"]) == 3
    assert g["moves"][-1]["outcome"] == "hit"
    assert g["moves"][-1]["detail"] == "被爆炸波及"


async def test_bomberman_double_plant_is_illegal(client):
    """同格已有炸弹再布雷 = 非法判负(默认 fuse=3 下第二颗落不下去)。"""
    user = await register_and_login(client, "bmbad")
    bots = [await _upload(client, user, "bomberman", "Planter", ALWAYS_PLANT),
            await _upload(client, user, "bomberman", "Passer", ALWAYS_PASS)]
    m = await _run_match(client, user, "bomberman", bots,
                         {"games_per_pairing": 1})
    g = m["result"]["games"][0]
    assert g["reason"] == "illegal" and g["winner"] == bots[1]
    assert len(g["moves"]) == 3


# ---- P1:光轮全流程(确定性基准) ----

async def test_tron_first_safe_duel(client):
    user = await register_and_login(client, "tronplayer")
    bots = [await _upload(client, user, "tron", "A", TRON_FIRST_SAFE),
            await _upload(client, user, "tron", "B", TRON_FIRST_SAFE)]
    m = await _run_match(client, user, "tron", bots, {"games_per_pairing": 1})
    g = m["result"]["games"][0]
    assert g["reason"] == "win" and g["winner"] == bots[1]
    assert len(g["moves"]) == 59                     # 58 步移动 + 最后撞墙
    assert g["moves"][-1]["outcome"] == "hit"
    assert g["moves"][-1]["detail"] == "撞墙"
    assert g["moves"][-1]["player"] == bots[0]
    first = g["moves"][0]
    assert first["board"][7 * 15] == 1 and first["board"][6 * 15] == 3  # 旧头留痕,向上出新头


# ---- P1+:炸弹人多人同局(3-4 人) ----

async def test_bomberman_four_player_planter_blows_up(client):
    """4 人局:fuse=1 下先手布雷者第 1 回合末自爆出局,其余三人活到回合耗尽。

    记录数 = 4 次行动 + 1 爆炸 + 19 回合 × 3 人 + 1 收尾 = 63。
    """
    user = await register_and_login(client, "bm4p")
    bots = [await _upload(client, user, "bomberman", "Planter", ALWAYS_PLANT),
            await _upload(client, user, "bomberman", "P1", ALWAYS_PASS),
            await _upload(client, user, "bomberman", "P2", ALWAYS_PASS),
            await _upload(client, user, "bomberman", "P3", ALWAYS_PASS)]
    m = await _run_match(client, user, "bomberman", bots,
                         {"games": 1, "fuse": 1, "max_rounds": 20})
    g = m["result"]["games"][0]
    assert g["players"] == bots and g["first"] == bots[0]
    assert g["reason"] == "draw" and g["winner"] is None
    assert len(g["moves"]) == 63
    assert g["moves"][4]["outcome"] == "hit"
    assert g["moves"][4]["detail"] == "被爆炸波及"
    assert g["ranking"] == [[bots[1], bots[2], bots[3]], [bots[0]]]
    assert m["result"]["scores"][str(bots[0])]["loss"] == 1
    assert m["result"]["scores"][str(bots[1])]["win"] == 1

    # 多人 ELO 经执行器落库:4 人都在榜且严格零和
    board = (await client.get("/api/v2/arena/leaderboard/bomberman",
                              headers=user)).json()["leaderboard"]
    assert len(board) == 4
    assert abs(sum(b["rating"] for b in board) - 4000.0) < 0.01
    ratings = {b["id"]: b for b in board}
    assert ratings[bots[0]]["losses"] == 1
    assert ratings[bots[1]]["wins"] == 1


async def test_bomberman_three_player_first_action(client):
    """3 人局结构断言:全员上榜、名次组覆盖全部 bot、ELO 零和。"""
    user = await register_and_login(client, "bm3p")
    bots = [await _upload(client, user, "bomberman", f"B{i}", BOMBER_FIRST_ACTION)
            for i in range(3)]
    m = await _run_match(client, user, "bomberman", bots,
                         {"games": 1, "seed": 7})
    g = m["result"]["games"][0]
    assert len(g["players"]) == 3 and g["players"] == bots
    assert g["reason"] in ("win", "draw")
    assert (g["winner"] in bots) if g["reason"] == "win" else (g["winner"] is None)
    ranked = [pid for grp in g["ranking"] for pid in grp]
    assert sorted(ranked) == sorted(bots)
    board = (await client.get("/api/v2/arena/leaderboard/bomberman",
                              headers=user)).json()["leaderboard"]
    assert len(board) == 3
    assert abs(sum(b["rating"] for b in board) - 3000.0) < 0.01
