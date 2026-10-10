# -*- coding: utf-8 -*-
"""API 依赖:DB 会话、当前用户、管理员门槛。"""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from ..context import AppContext
from ..core import errors
from ..core.security import decode_access_token
from ..db.models import User

_bearer = HTTPBearer(auto_error=False)


def get_ctx(request: Request) -> AppContext:
    return request.app.state.ctx


async def get_db(request: Request):
    ctx: AppContext = request.app.state.ctx
    async with ctx.session_factory() as session:
        yield session


CtxDep = Annotated[AppContext, Depends(get_ctx)]
DbDep = Annotated[AsyncSession, Depends(get_db)]


async def current_user(request: Request, db: DbDep,
                       creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
                       ) -> User:
    """强制鉴权:仅接受本后端签发的 JWT(官方平台令牌签名不同,必然拒绝)。"""
    ctx: AppContext = request.app.state.ctx
    if creds is None or not creds.credentials:
        raise errors.auth_required()
    payload = decode_access_token(creds.credentials, ctx.settings.jwt_secret)
    user = await db.get(User, int(payload["sub"]))
    if user is None:
        raise errors.auth_required()
    return user


UserDep = Annotated[User, Depends(current_user)]


async def require_admin(user: UserDep) -> User:
    if user.role != "admin":
        raise errors.auth_forbidden("需要管理员权限")
    return user


AdminDep = Annotated[User, Depends(require_admin)]


async def optional_user(request: Request, db: DbDep,
                        creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
                        ) -> User | None:
    """可选鉴权:公开端点用;带令牌且有效则给出用户。"""
    if creds is None or not creds.credentials:
        return None
    try:
        ctx: AppContext = request.app.state.ctx
        payload = decode_access_token(creds.credentials, ctx.settings.jwt_secret)
        return await db.get(User, int(payload["sub"]))
    except errors.NovaError:
        return None
