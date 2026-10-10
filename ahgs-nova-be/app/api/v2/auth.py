# -*- coding: utf-8 -*-
"""v2 认证:注册/登录/刷新/登出/我(安全报告 §4/§5 欠账在本层一次还清)。"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request
from sqlalchemy import select

from ...core import errors
from ...core.audit import audit
from ...core.security import (
    hash_password, issue_access_token, new_refresh_token, now_utc, verify_password,
)
from ...db.models import RefreshToken, User
from ...schemas import LoginIn, RefreshIn, RegisterIn
from ..deps import DbDep, UserDep

router = APIRouter(prefix="/api/v2/auth", tags=["v2-auth"])


def user_brief(u: User) -> dict:
    return {"id": u.id, "username": u.username,
            "display_name": u.display_name or u.username, "role": u.role,
            "created_at": u.created_at.isoformat() if u.created_at else None}


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "-"


def _refresh_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


async def _issue_pair(ctx, db, user: User) -> dict:
    access = issue_access_token(
        user.id, user.username, user.role, ctx.settings.jwt_secret,
        ctx.settings.access_token_minutes,
    )
    raw, token_hash = new_refresh_token()
    db.add(RefreshToken(
        user_id=user.id, token_hash=token_hash,
        expires_at=now_utc() + timedelta(days=ctx.settings.refresh_token_days),
        created_at=now_utc(),
    ))
    await db.commit()
    return {
        "access_token": access, "refresh_token": raw, "token_type": "bearer",
        "expires_in": ctx.settings.access_token_minutes * 60,
        "user": user_brief(user),
    }


async def _get_user(db, username: str) -> User | None:
    return (await db.scalars(
        select(User).where(User.username == username)
    )).first()


async def _get_refresh_row(db, raw: str) -> RefreshToken | None:
    return (await db.scalars(
        select(RefreshToken).where(RefreshToken.token_hash == _refresh_hash(raw))
    )).first()


@router.post("/register", status_code=201)
async def register(body: RegisterIn, request: Request, db: DbDep):
    """注册(同 IP 高频注册限速;用户名唯一)。"""
    ctx = request.app.state.ctx
    ip = _client_ip(request)
    locked, unlock_at = ctx.limiter.is_locked("register", ip)
    if locked:
        raise errors.NovaError("RATE_LIMITED", "注册过于频繁,请稍后再试", 429,
                               detail={"retry_after_epoch": unlock_at})
    if await _get_user(db, body.username):
        raise errors.conflict("USERNAME_TAKEN", "用户名已存在")
    user = User(username=body.username, display_name=body.display_name,
                role="user", password_hash=hash_password(body.password),
                created_at=now_utc())
    db.add(user)
    await db.flush()
    await audit(db, actor=body.username, action="auth.register",
                target=f"user:{user.id}", detail={"ip": ip})
    await db.commit()
    return {"id": user.id, "username": user.username, "display_name": user.display_name}


@router.post("/login")
async def login(body: LoginIn, request: Request, db: DbDep):
    """登录(失败 5 次锁 15 分钟,按账号+IP 双维度)。"""
    ctx = request.app.state.ctx
    ip = _client_ip(request)
    for parts in ((body.username, ip), (body.username, ""), ("", ip)):
        locked, unlock_at = ctx.limiter.is_locked(*parts)
        if locked:
            raise errors.account_locked(
                datetime.fromtimestamp(unlock_at, tz=timezone.utc)
                .replace(tzinfo=None).isoformat())

    user = await _get_user(db, body.username)
    if user is None or not verify_password(body.password, user.password_hash):
        ctx.limiter.record_failure(body.username, ip)
        ctx.limiter.record_failure(body.username, "")
        ctx.limiter.record_failure("", ip)
        await audit(db, actor=body.username, action="auth.login_failed",
                    detail={"ip": ip})
        await db.commit()
        raise errors.bad_credentials()

    ctx.limiter.record_success(body.username, ip)
    await audit(db, actor=user.username, action="auth.login", detail={"ip": ip})
    return await _issue_pair(ctx, db, user)


@router.post("/refresh")
async def refresh(body: RefreshIn, request: Request, db: DbDep):
    """刷新令牌轮换:旧 token 一次性作废。"""
    ctx = request.app.state.ctx
    row = await _get_refresh_row(db, body.refresh_token)
    if row is None or row.revoked or row.expires_at < now_utc():
        raise errors.auth_required()
    user = await db.get(User, row.user_id)
    if user is None:
        raise errors.auth_required()
    row.revoked = True
    return await _issue_pair(ctx, db, user)


@router.post("/logout")
async def logout(body: RefreshIn, db: DbDep, user: UserDep):
    row = await _get_refresh_row(db, body.refresh_token)
    if row and row.user_id == user.id:
        row.revoked = True
        await db.commit()
    return {"ok": True}


@router.get("/me")
async def me(user: UserDep):
    return user_brief(user)
