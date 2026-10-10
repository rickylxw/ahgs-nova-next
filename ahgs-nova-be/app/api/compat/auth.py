# -*- coding: utf-8 -*-
"""兼容层(standalone 模式):/api/auth/* 与官方契约同形。

安全修复随层生效:限速锁定、密码哈希、短效 JWT;注册/登录载荷对官方
多余字段(confirm_password/agree_terms)宽容。
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import select

from ...core import errors
from ...core.audit import audit
from ...core.security import (
    hash_password, issue_access_token, now_utc, verify_password,
)
from ...db.models import User
from ..deps import DbDep, UserDep
from ..v2.auth import user_brief

router = APIRouter(tags=["compat-auth"])


class _CompatLogin(BaseModel):
    model_config = {"extra": "allow"}
    username: str
    password: str


class _CompatRegister(BaseModel):
    model_config = {"extra": "allow"}
    username: str
    password: str
    display_name: str = ""


class _CompatMePatch(BaseModel):
    model_config = {"extra": "allow"}
    display_name: str | None = None
    email: str | None = None
    avatar: str | None = None


class _CompatPassword(BaseModel):
    model_config = {"extra": "allow"}
    old_password: str
    new_password: str


@router.post("/api/auth/login")
async def login(body: _CompatLogin, request: Request, db: DbDep):
    ctx = request.app.state.ctx
    ip = request.client.host if request.client else "-"
    for parts in ((body.username, ip), (body.username, ""), ("", ip)):
        locked, unlock_at = ctx.limiter.is_locked(*parts)
        if locked:
            from datetime import datetime, timezone
            raise errors.account_locked(
                datetime.fromtimestamp(unlock_at, tz=timezone.utc)
                .replace(tzinfo=None).isoformat())

    user = (await db.scalars(
        select(User).where(User.username == body.username))).first()
    if user is None or not verify_password(body.password, user.password_hash):
        for parts in ((body.username, ip), (body.username, ""), ("", ip)):
            ctx.limiter.record_failure(*parts)
        await audit(db, actor=body.username, action="auth.login_failed",
                    detail={"ip": ip, "via": "compat"})
        await db.commit()
        raise errors.bad_credentials()
    ctx.limiter.record_success(body.username, ip)
    await audit(db, actor=user.username, action="auth.login",
                detail={"ip": ip, "via": "compat"})
    token = issue_access_token(user.id, user.username, user.role,
                               ctx.settings.jwt_secret,
                               ctx.settings.access_token_minutes)
    await db.commit()
    # 官方契约:{access_token, user};NOVA 前端 setSession(access_token, user)
    return {"access_token": token, "token_type": "bearer", "user": user_brief(user)}


@router.post("/api/auth/register", status_code=201)
async def register(body: _CompatRegister, request: Request, db: DbDep):
    ctx = request.app.state.ctx
    ip = request.client.host if request.client else "-"
    locked, _ = ctx.limiter.is_locked("register", ip)
    if locked:
        raise errors.NovaError("RATE_LIMITED", "注册过于频繁,请稍后再试", 429)
    if len(body.password) < 8:
        raise errors.invalid_input("密码至少 8 位")
    exists = (await db.scalars(
        select(User).where(User.username == body.username))).first()
    if exists:
        raise errors.conflict("USERNAME_TAKEN", "用户名已存在")
    user = User(username=body.username, display_name=body.display_name,
                role="user", password_hash=hash_password(body.password),
                created_at=now_utc())
    db.add(user)
    await db.flush()
    await audit(db, actor=body.username, action="auth.register",
                target=f"user:{user.id}", detail={"via": "compat"})
    await db.commit()
    return user_brief(user)


@router.get("/api/auth/me")
async def me(user: UserDep):
    return user_brief(user)


@router.patch("/api/auth/me")
async def patch_me(body: _CompatMePatch, db: DbDep, user: UserDep):
    if body.display_name is not None:
        user.display_name = body.display_name
    profile = dict(user.profile or {})
    if body.email is not None:
        profile["email"] = body.email
    if body.avatar is not None:
        profile["avatar"] = body.avatar
    user.profile = profile
    await db.commit()
    return user_brief(user)


@router.post("/api/auth/me/password")
async def change_password(body: _CompatPassword, db: DbDep, user: UserDep):
    if not verify_password(body.old_password, user.password_hash):
        raise errors.bad_credentials()
    if len(body.new_password) < 8:
        raise errors.invalid_input("新密码至少 8 位")
    user.password_hash = hash_password(body.new_password)
    await audit(db, actor=user.username, action="auth.password_change")
    await db.commit()
    return {"ok": True}
