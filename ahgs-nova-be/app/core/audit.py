# -*- coding: utf-8 -*-
"""审计日志辅助(计划 §5:audit_log 表)。"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import AuditLog
from .security import now_utc


async def audit(db: AsyncSession, actor: str, action: str,
                target: str = "", detail: dict[str, Any] | None = None) -> None:
    db.add(AuditLog(actor=actor, action=action, target=target,
                    detail=detail or {}, created_at=now_utc()))
