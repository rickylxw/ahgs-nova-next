# -*- coding: utf-8 -*-
"""v2 Arena:上传对战程序、约战、对局查询、ELO 榜(对战小游戏玩法的全部入口)。

新增游戏只需实现 Arena 协议并注册(内置或 NOVA_ARENA_PLUGINS 插件),
本路由对所有游戏通用。
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import select

from ...core import errors
from ...core.audit import audit
from ...core.security import now_utc
from ...db.models import Bot, Match, Problem
from ...schemas import BotIn, MatchIn
from ...services.executors.base import RunSecrets
from ..deps import DbDep, UserDep

router = APIRouter(prefix="/api/v2/arena", tags=["v2-arena"])


def bot_dict(b: Bot, include_code: bool = False) -> dict:
    d = {
        "id": b.id, "arena_key": b.arena_key, "name": b.name,
        "user_id": b.user_id, "lang": b.lang, "active": b.active,
        "rating": b.rating, "wins": b.wins, "losses": b.losses,
        "draws": b.draws,
        "created_at": b.created_at.isoformat() if b.created_at else None,
    }
    if include_code:
        d["code"] = b.code
    return d


def match_dict(m: Match, include_result: bool = False) -> dict:
    d = {
        "id": m.id, "run_id": m.run_id, "arena_key": m.arena_key,
        "user_id": m.user_id, "bot_ids": m.bot_ids, "status": m.status,
        "config": m.config, "error_code": m.error_code,
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "finished_at": m.finished_at.isoformat() if m.finished_at else None,
    }
    if include_result:
        d["result"] = m.result
    return d


# ---- 游戏目录 ----

@router.get("/arenas")
async def list_arenas(request: Request):
    ctx = request.app.state.ctx
    return {"arenas": ctx.arenas.list()}


# ---- Bot 管理 ----

@router.get("/bots")
async def list_bots(db: DbDep, user: UserDep, arena_key: str | None = None,
                    mine: bool = False, limit: int = 100):
    q = select(Bot).order_by(Bot.rating.desc()).limit(min(limit, 500))
    if arena_key:
        q = q.where(Bot.arena_key == arena_key)
    if mine:
        q = q.where(Bot.user_id == user.id)
    rows = (await db.scalars(q)).all()
    return {"bots": [bot_dict(b) for b in rows]}


@router.post("/bots", status_code=201)
async def upload_bot(body: BotIn, request: Request, db: DbDep, user: UserDep):
    """上传对战程序(源码;执行在受限子进程,生产路径为 Docker 沙箱池)。"""
    ctx = request.app.state.ctx
    arena = ctx.arenas.get(body.arena_key)  # 未注册游戏 → ARENA_NOT_FOUND
    bot = Bot(user_id=user.id, arena_key=body.arena_key, name=body.name,
              code=body.code, lang=body.lang, created_at=now_utc(),
              updated_at=now_utc())
    db.add(bot)
    await db.flush()
    await audit(db, actor=user.username, action="arena.bot_upload",
                target=f"bot:{bot.id}", detail={"arena": body.arena_key})
    await db.commit()
    return bot_dict(bot, include_code=False)


@router.get("/bots/{bot_id}")
async def get_bot(bot_id: int, db: DbDep, user: UserDep):
    bot = await db.get(Bot, bot_id)
    if bot is None:
        raise errors.not_found("bot", bot_id)
    include_code = bot.user_id == user.id or user.role == "admin"
    return bot_dict(bot, include_code=include_code)


@router.post("/bots/{bot_id}/deactivate")
async def deactivate_bot(bot_id: int, request: Request, db: DbDep, user: UserDep):
    bot = await db.get(Bot, bot_id)
    if bot is None:
        raise errors.not_found("bot", bot_id)
    if bot.user_id != user.id and user.role != "admin":
        raise errors.auth_forbidden("只能管理自己的 bot")
    bot.active = False
    bot.updated_at = now_utc()
    await audit(db, actor=user.username, action="arena.bot_deactivate",
                target=f"bot:{bot.id}")
    await db.commit()
    return bot_dict(bot)


# ---- 约战 ----

@router.post("/matches", status_code=201)
async def create_match(body: MatchIn, request: Request, db: DbDep, user: UserDep):
    """创建对阵并入队执行;观战走 WS /api/v2/ws/runs/{run_id}。"""
    ctx = request.app.state.ctx
    arena = ctx.arenas.get(body.arena_key)
    if len(set(body.bot_ids)) != len(body.bot_ids):
        raise errors.invalid_input("bot_ids 有重复")
    if len(body.bot_ids) < arena.min_bots:
        raise errors.invalid_input(
            f"{arena.display_name} 至少需要 {arena.min_bots} 个 bot")
    if len(body.bot_ids) > arena.max_bots:
        raise errors.invalid_input(
            f"{arena.display_name} 最多允许 {arena.max_bots} 个 bot")
    bots = []
    for bid in body.bot_ids:
        bot = await db.get(Bot, int(bid))
        if bot is None or not bot.active:
            raise errors.not_found("bot", bid)
        if bot.arena_key != body.arena_key:
            raise errors.invalid_input(
                f"bot {bid} 不属于游戏 {body.arena_key}")
        bots.append(bot)

    match = Match(user_id=user.id, arena_key=body.arena_key,
                  config=arena.merge_config(body.config),
                  bot_ids=list(body.bot_ids), created_at=now_utc())
    db.add(match)
    await db.flush()

    run = await ctx.orchestrator.enqueue_run(
        db, user_id=user.id, kind="arena_match",
        config={"match_id": match.id},
        secrets=RunSecrets(),
    )
    match.run_id = run.id
    await db.flush()
    await audit(db, actor=user.username, action="arena.match_create",
                target=f"match:{match.id}", detail={"run_id": run.id})
    await db.commit()
    return {**match_dict(match), "run_id": run.id}


@router.get("/matches")
async def list_matches(db: DbDep, user: UserDep, arena_key: str | None = None,
                       limit: int = 50):
    q = select(Match).order_by(Match.id.desc()).limit(min(limit, 200))
    if arena_key:
        q = q.where(Match.arena_key == arena_key)
    rows = (await db.scalars(q)).all()
    return {"matches": [match_dict(m) for m in rows]}


@router.get("/matches/{match_id}")
async def get_match(match_id: int, db: DbDep, user: UserDep):
    match = await db.get(Match, match_id)
    if match is None:
        raise errors.not_found("比赛", match_id)
    return match_dict(match, include_result=match.status == "completed")


# ---- ELO 榜 ----

@router.get("/leaderboard/{arena_key}")
async def leaderboard(arena_key: str, request: Request, db: DbDep, user: UserDep):
    request.app.state.ctx.arenas.get(arena_key)  # 校验游戏存在
    rows = (await db.scalars(
        select(Bot).where(Bot.arena_key == arena_key, Bot.active == True)  # noqa: E712
        .order_by(Bot.rating.desc()).limit(200)
    )).all()
    return {
        "arena_key": arena_key,
        "leaderboard": [
            {**bot_dict(b, include_code=False), "rank": i + 1,
             "games": b.wins + b.losses + b.draws}
            for i, b in enumerate(rows)
        ],
    }
