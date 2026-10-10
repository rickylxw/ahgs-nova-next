# -*- coding: utf-8 -*-
"""登录/注册限速(计划 §4.1:5 次失败锁 15 分钟,按账号+IP 双维度)。

进程内滑动窗口实现;多实例部署时可换 Redis 后端(接口不变)。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class _FailureState:
    timestamps: list[float] = field(default_factory=list)
    locked_until: float = 0.0


class RateLimiter:
    """失败计数 + 锁定。成功登录会清零对应账号计数。"""

    def __init__(self, max_failures: int = 5, lockout_seconds: int = 900,
                 window_seconds: int = 900):
        self.max_failures = max_failures
        self.lockout_seconds = lockout_seconds
        self.window_seconds = window_seconds
        self._states: dict[str, _FailureState] = {}

    # ---- 内部 ----

    @staticmethod
    def _key(*parts: str) -> str:
        return "|".join(p or "-" for p in parts)

    def _state(self, key: str) -> _FailureState:
        return self._states.setdefault(key, _FailureState())

    def _prune(self, st: _FailureState, now: float) -> None:
        cutoff = now - self.window_seconds
        st.timestamps = [t for t in st.timestamps if t > cutoff]

    # ---- 对外 ----

    def is_locked(self, *parts: str) -> tuple[bool, float]:
        """返回 (是否锁定, 解锁 epoch 秒)。"""
        now = time.time()
        st = self._state(self._key(*parts))
        if st.locked_until > now:
            return True, st.locked_until
        return False, 0.0

    def record_failure(self, *parts: str) -> bool:
        """记一次失败;达到阈值则触发锁定,返回是否刚触发锁定。"""
        now = time.time()
        st = self._state(self._key(*parts))
        if st.locked_until > now:
            return False
        self._prune(st, now)
        st.timestamps.append(now)
        if len(st.timestamps) >= self.max_failures:
            st.locked_until = now + self.lockout_seconds
            st.timestamps.clear()
            return True
        return False

    def record_success(self, *parts: str) -> None:
        """成功登录清除该账号(及各 IP 维度)的失败计数。"""
        # 精确清账号维度的 key;IP 维度的计数随窗口自然过期
        self._states.pop(self._key(*parts), None)

    def reset_all(self) -> None:
        self._states.clear()
