# -*- coding: utf-8 -*-
"""运行执行器协议(可插拔负载的核心)。

每种工作负载(evolve_official / evolve_local / arena_match / grind / abtest / …)
实现一个 RunExecutor 并向 Orchestrator 注册;编排器按 runs.kind 分派,不做业务。
新增一种负载 = 新增一个执行器文件 + 一行注册,编排器与 API 层零改动。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:  # 避免循环导入
    from ..orchestrator import Orchestrator
    from ...db.models import Run


@dataclass
class RunSecrets:
    """随请求传入、不落库的敏感参数(个人 LLM key 用后即弃)。"""

    llm_api_key: str = ""
    extra: dict[str, str] = field(default_factory=dict)


@dataclass
class RunContext:
    db: AsyncSession
    run: "Run"
    orchestrator: "Orchestrator"
    secrets: RunSecrets

    # ---- 快捷通道 ----

    @property
    def settings(self):
        return self.orchestrator.settings

    async def emit(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        await self.orchestrator.emit_event(self.run.id, event_type, data)

    async def set_generation(self, generation: int, best: float | None,
                             snapshot: dict[str, Any]) -> None:
        """落一代全量种群并推送 generation_end(计划 §4.2/§4.3)。"""
        await self.orchestrator.record_generation(
            self.db, self.run, generation, best, snapshot
        )


class RunExecutor:
    """执行器基类:子类设 kind 并实现 execute();可选实现 cancel()。"""

    kind = "abstract"

    async def execute(self, ctx: RunContext) -> dict[str, Any]:  # pragma: no cover
        raise NotImplementedError

    async def cancel(self, ctx: RunContext) -> None:
        """尽力协作式取消;默认无操作(编排器随后强制取消任务)。"""
        return None
