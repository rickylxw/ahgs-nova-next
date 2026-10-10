# -*- coding: utf-8 -*-
"""结构化错误(计划 §4.2:替代 detail 字符串匹配)。

所有 v2 端点抛出的业务错误都是 NovaError;全局异常处理器把它渲染为
``{"code": ..., "message": ..., "retryable": ..., "detail": ...}`` 信封。
"""
from __future__ import annotations

from typing import Any


class NovaError(Exception):
    """带结构化错误码的业务异常。"""

    def __init__(
        self,
        code: str,
        message: str,
        status: int = 400,
        retryable: bool = False,
        detail: Any = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.retryable = retryable
        self.detail = detail

    def envelope(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "detail": self.detail,
        }


# ---- 常用错误工厂(统一错误码,便于自动化识别) ----

def auth_required() -> NovaError:
    return NovaError("AUTH_REQUIRED", "未登录或令牌已过期", 401)


def auth_forbidden(msg: str = "无权限") -> NovaError:
    return NovaError("AUTH_FORBIDDEN", msg, 403)


def bad_credentials() -> NovaError:
    return NovaError("AUTH_BAD_CREDENTIALS", "用户名或密码错误", 401)


def account_locked(unlock_at: str) -> NovaError:
    return NovaError(
        "AUTH_LOCKED", f"失败次数过多,账号已锁定至 {unlock_at}", 423,
        detail={"unlock_at": unlock_at},
    )


def not_found(what: str, ident: Any = None) -> NovaError:
    return NovaError("NOT_FOUND", f"{what}不存在", 404, detail={"target": str(ident)})


def conflict(code: str, message: str, detail: Any = None) -> NovaError:
    return NovaError(code, message, 409, detail=detail)


def quota_exceeded(message: str, detail: Any = None) -> NovaError:
    return NovaError("QUOTA_EXCEEDED", message, 429, detail=detail)


def queue_paused(reason: str, until: str) -> NovaError:
    """显式的"数据保护中"等价语义(计划痛点 #5):有预告、有原因、有恢复时间。"""
    return NovaError(
        "QUEUE_PAUSED", f"队列已暂停:{reason}", 503,
        detail={"reason": reason, "resume_at": until},
    )


def invalid_input(message: str, detail: Any = None) -> NovaError:
    return NovaError("INVALID_INPUT", message, 422, detail=detail)
