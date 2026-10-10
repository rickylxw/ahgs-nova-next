# -*- coding: utf-8 -*-
"""认证与密码(JWT + PBKDF2)。

- 访问令牌:HS256 JWT,默认 2h(计划 §4.1:替代官方 38 天长效令牌)。
- 刷新令牌:不透明随机串,哈希落库,可吊销。
- 密码:PBKDF2-HMAC-SHA256,标准库实现,免 C 扩展依赖、跨平台稳定。
- 时间语义:令牌内 exp 用 UTC 时间戳;对外 API 一律输出 naive UTC ISO 字符串。
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from datetime import datetime, timedelta, timezone

import jwt

from .errors import auth_required

JWT_ALG = "HS256"
_PBKDF2_ITERATIONS = 240_000


# ---------- 密码 ----------

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iters, salt_hex, dk_hex = stored.split("$")
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iters)
        )
        return hmac.compare_digest(dk.hex(), dk_hex)
    except (ValueError, TypeError):
        return False


# ---------- 访问令牌 ----------

def issue_access_token(user_id: int, username: str, role: str, secret: str,
                       minutes: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=minutes),
    }
    return jwt.encode(payload, secret, algorithm=JWT_ALG)


def decode_access_token(token: str, secret: str) -> dict:
    try:
        return jwt.decode(token, secret, algorithms=[JWT_ALG])
    except jwt.ExpiredSignatureError:
        raise auth_required() from None
    except jwt.PyJWTError:
        raise auth_required() from None


# ---------- 刷新令牌(哈希落库,可吊销) ----------

def new_refresh_token() -> tuple[str, str]:
    """返回 (明文 token, 落库哈希)。"""
    raw = secrets.token_urlsafe(48)
    return raw, _hash_refresh(raw)


def _hash_refresh(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def check_refresh_hash(raw: str, stored: str) -> bool:
    return hmac.compare_digest(_hash_refresh(raw), stored)


# ---------- 时间约定 ----------

def now_utc() -> datetime:
    """naive UTC(与官方平台契约一致,前端 parseServerTime() 按 UTC 解析)。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso_utc(dt: datetime | None = None) -> str:
    return (dt or now_utc()).isoformat()


def epoch_now() -> int:
    return int(time.time())
