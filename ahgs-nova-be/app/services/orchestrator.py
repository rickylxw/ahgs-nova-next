# -*- coding: utf-8 -*-
"""运行编排器(计划 §4.2:替代官方"并发 20 + 400"的裸线程实现)。

- 状态机:queued → running → completed|failed|canceled,转移全程落库。
- 优先级队列 + 单用户并发上限(可配置,替代一刀切)。
- 队列暂停为显式状态(计划痛点 #5"数据保护中"的等价物):有原因、有恢复预告。
- 事件推送:每次转移与每代结束发事件,WS 订阅直达。
- 执行器按 runs.kind 从注册表分派;编排器只管生命周期,不懂业务。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..core import errors
from ..core.audit import audit
from ..core.config import Settings
from ..core.security import now_utc, iso_utc
from ..db.models import Generation, Problem, Run, Submission, User
from ..db.models import RUN_STATUSES, TERMINAL_STATUSES
from .events import EventBus
from .executors.base import RunContext, RunExecutor, RunSecrets
from .queue import QueueBackend

log = logging.getLogger("nova.orchestrator")

ACTIVE_STATUSES = ("queued", "running")
# 完成后自动提交的运行类型(NOVA_AUTO_SUBMIT 开启时)
async def auto_submit_run(db: AsyncSession, settings: Settings, run: Run,
                          emit=None) -> int | None:
    """运行完成自动提交(NOVA_AUTO_SUBMIT 开启时)。返回 submission_id 或 None。

    构造逻辑与 compat/evolution.py 的手动 submit 一致(detail.instance.config
    与 best_heuristic);同一 run 已有提交则跳过;罚值最优(违规垃圾)不提交;
    动作写审计日志。
    """
    if not settings.auto_submit or run.kind not in AUTO_SUBMIT_KINDS:
        return None
    if not run.problem_key:
        return None
    result = run.result or {}
    obj = result.get("best_objective")
    if not isinstance(obj, (int, float)):
        return None
    if abs(obj) >= PENALTY:
        log.info("运行 %s best_objective 为罚值,跳过自动提交", run.id)
        return None
    existing = await db.scalar(
        select(Submission).where(Submission.run_id == run.id))
    if existing is not None:
        return existing.id
    problem = await db.get(Problem, run.problem_key)
    user = await db.get(User, run.user_id)
    sub = Submission(
        user_id=run.user_id, problem_key=run.problem_key, run_id=run.id,
        objective=float(obj), is_official=True,
        detail={"instance": {"config": {
            "ascend": run.config.get("ascend",
                                     problem.ascend if problem else True),
            "problem_key": run.problem_key,
        }}, "result": {"best_heuristic": result.get("best_heuristic")}},
        created_at=now_utc(),
    )
    db.add(sub)
    await db.flush()
    await audit(db, actor=user.username if user else f"user:{run.user_id}",
                action="submission.auto", target=f"submission:{sub.id}",
                detail={"run_id": run.id, "problem_key": run.problem_key,
                        "objective": float(obj)})
    if emit is not None:
        await emit("submission_auto_created",
                   {"submission_id": sub.id, "objective": float(obj)})
    log.info("运行 %s 自动提交 submission=%s objective=%s", run.id, sub.id, obj)
    return sub.id



# 完成后自动提交的运行类型(NOVA_AUTO_SUBMIT 开启时)
AUTO_SUBMIT_KINDS = ("evolve_llm", "evolve_local", "evolve_official")
# 裁判罚值约定(违规候选 objective),与题目契约/引擎一致
PENALTY = 10 ** 9


class Orchestrator:
    def __init__(self, settings: Settings, session_factory: async_sessionmaker[AsyncSession],
                 bus: EventBus, queue: QueueBackend, n_workers: int = 4,
                 storage=None, llm_gateway=None):
        self.settings = settings
        self.session_factory = session_factory
        self.bus = bus
        self.queue = queue
        self.n_workers = n_workers
        self.storage = storage          # services.storage.LocalStorage(执行器可选用)
        self.llm = llm_gateway          # services.llm.LLMGateway(执行器可选用)
        self.executors: dict[str, RunExecutor] = {}
        self._tasks: dict[int, asyncio.Task] = {}
        self._done: dict[int, asyncio.Event] = {}
        self._secrets: dict[int, RunSecrets] = {}
        self._workers: list[asyncio.Task] = []
        self._stopping = False
        # SQLite 开发库下,读写并发事务存在"读后写升级锁"的 BUSY 窗口:
        # 把最热的每代快照写路径在进程内串行化(单事件循环内零成本,Postgres 无需)
        self._gen_write_lock = asyncio.Lock()

    # ============ 执行器注册 ============

    def register_executor(self, executor: RunExecutor) -> None:
        if executor.kind in self.executors:
            raise ValueError(f"执行器重复注册: {executor.kind}")
        self.executors[executor.kind] = executor

    # ============ 生命周期 ============

    async def start(self) -> None:
        self._stopping = False
        for i in range(self.n_workers):
            self._workers.append(asyncio.create_task(self._worker(i), name=f"nova-worker-{i}"))

    async def stop(self) -> None:
        self._stopping = True
        for t in self._workers:
            t.cancel()
        for task in list(self._tasks.values()):
            task.cancel()
        await asyncio.gather(*self._workers, *self._tasks.values(), return_exceptions=True)
        self._workers.clear()
        self._tasks.clear()

    # ============ 入队 ============

    async def enqueue_run(
        self,
        db: AsyncSession,
        *,
        user_id: int,
        kind: str,
        problem_key: str | None = None,
        problem_kind: str | None = None,
        config: dict[str, Any] | None = None,
        priority: int = 0,
        total_generations: int = 0,
        seed_id: int | None = None,
        parent_run_id: int | None = None,
        secrets: RunSecrets | None = None,
        commit: bool = True,
    ) -> Run:
        self._assert_run_kind_allowed(problem_kind, kind)

        if self.settings.queue_paused and parent_run_id is None:
            raise errors.queue_paused(
                self.settings.queue_pause_reason or "平台维护",
                self.settings.queue_pause_until or "待通知",
            )

        if self.settings.max_concurrent_per_user > 0:
            n = await db.scalar(
                select(func.count(Run.id)).where(
                    Run.user_id == user_id, Run.status.in_(ACTIVE_STATUSES)
                )
            )
            if n >= self.settings.max_concurrent_per_user:
                raise errors.quota_exceeded(
                    f"并发运行数已达上限({self.settings.max_concurrent_per_user})",
                    detail={"active": n},
                )

        run = Run(
            user_id=user_id, problem_key=problem_key, kind=kind, status="queued",
            priority=priority, config=config or {}, total_generations=total_generations,
            seed_id=seed_id, parent_run_id=parent_run_id, created_at=now_utc(),
        )
        db.add(run)
        await db.flush()
        if secrets and (secrets.llm_api_key or secrets.extra):
            self._secrets[run.id] = secrets
        # 先落库可见再入队:worker 在独立连接上取活,看不见未提交的行
        if commit:
            await db.commit()
        await self.queue.enqueue(run.id, priority)
        await self.emit_event(run.id, "run_queued", self._run_brief(run))
        return run

    # 复合负载(自身就是编排器的负载,不绑定题目类型)
    COMPOSITE_RUN_KINDS = ("grind", "abtest")

    @classmethod
    def _assert_run_kind_allowed(cls, problem_kind: str | None, kind: str) -> None:
        if kind in cls.COMPOSITE_RUN_KINDS:
            return
        from .registry import get_problem_kind  # 延迟导入避免循环

        if problem_kind is not None:
            spec = get_problem_kind(problem_kind)
            if spec is not None and kind not in spec.allowed_run_kinds:
                raise errors.invalid_input(
                    f"题目类型 {problem_kind} 不支持运行类型 {kind}",
                    detail={"problem_kind": problem_kind, "kind": kind,
                            "allowed": list(spec.allowed_run_kinds)},
                )

    # ============ 事件 ============

    async def emit_event(self, run_id: int, event_type: str,
                         data: dict[str, Any] | None = None,
                         db: AsyncSession | None = None, commit: bool = False) -> None:
        event = {"type": event_type, "run_id": run_id, "data": data or {}, "ts": iso_utc()}
        self.bus.publish(str(run_id), event)
        self.bus.publish("*", event)
        if db is not None and commit:
            await db.commit()

    async def record_generation(self, db: AsyncSession, run: Run, generation: int,
                                best: float | None, snapshot: dict[str, Any]) -> None:
        async with self._gen_write_lock:
            row = await db.scalar(
                select(Generation).where(
                    Generation.run_id == run.id, Generation.generation == generation
                )
            )
            if row is None:
                row = Generation(run_id=run.id, generation=generation, created_at=now_utc())
                db.add(row)
            row.best_objective = best
            row.snapshot = snapshot
            run.current_generation = max(run.current_generation, generation)
            if best is not None and self._better(best, run.best_objective,
                                                 run.config.get("ascend", True)):
                run.best_objective = best
            try:
                await db.commit()
            except Exception:
                await db.rollback()
                raise
        await self.emit_event(run.id, "generation_end", {
            "generation": generation, "best_objective": best,
            "current_generation": run.current_generation,
            "total_generations": run.total_generations,
            "snapshot": snapshot,
        })

    @staticmethod
    def _better(candidate: float, incumbent: float | None, ascend: bool) -> bool:
        """ascend=True → 越小越好(官方语义:ascend !== false)。"""
        if incumbent is None:
            return True
        return candidate < incumbent if ascend else candidate > incumbent

    @staticmethod
    def _run_brief(run: Run) -> dict[str, Any]:
        return {
            "run_id": run.id, "kind": run.kind, "status": run.status,
            "problem_key": run.problem_key, "user_id": run.user_id,
            "current_generation": run.current_generation,
            "total_generations": run.total_generations,
            "best_objective": run.best_objective,
        }

    # ============ 查询/等待 ============

    def is_terminal(self, status: str) -> bool:
        return status in TERMINAL_STATUSES

    async def wait_for_run(self, run_id: int, timeout: float | None = None) -> bool:
        """等待某运行到达终态(测试/编排用)。返回是否在时限内完成。"""
        ev = self._done.get(run_id)
        if ev is None:
            ev = asyncio.Event()
            ev = self._done.setdefault(run_id, ev)
            # 事件已注册:此后任务完成必会 set;再查一次库覆盖"注册前已完成"的窗口
            async with self.session_factory() as db:
                run = await db.get(Run, run_id)
            if run is None or self.is_terminal(run.status):
                if self._done.get(run_id) is ev and not ev.is_set():
                    self._done.pop(run_id, None)
                return True
        try:
            await asyncio.wait_for(ev.wait(), timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def wait_idle(self, timeout: float | None = None) -> bool:
        """等待队列清空且无活跃任务(测试/优雅退出用)。"""
        async def _idle() -> None:
            while self.queue.depth > 0 or self._tasks:
                await asyncio.sleep(0.02)
        try:
            await asyncio.wait_for(_idle(), timeout)
            return True
        except asyncio.TimeoutError:
            return False

    def active_count(self) -> int:
        return len(self._tasks)

    # ============ 取消 ============

    async def request_cancel(self, run_id: int) -> str:
        """取消运行;返回最终状态。"""
        async with self.session_factory() as db:
            run = await db.get(Run, run_id)
            if run is None:
                raise errors.not_found("运行", run_id)
            if self.is_terminal(run.status):
                return run.status
            kind = run.kind
        task = self._tasks.get(run_id)
        if task is not None and not task.done():
            # 协作式取消:给执行器机会清理上游资源
            async with self.session_factory() as db:
                run = await db.get(Run, run_id)
                ctx = RunContext(db=db, run=run,
                                 orchestrator=self,
                                 secrets=self._secrets.get(run_id, RunSecrets()))
                executor = self.executors.get(kind)
                if executor is not None:
                    try:
                        await asyncio.wait_for(executor.cancel(ctx), timeout=10)
                    except Exception:  # noqa: BLE001 — 取消清理失败不阻塞
                        log.warning("执行器 cancel 异常 run=%s", run_id, exc_info=True)
            task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=15)
            except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                pass
            return "canceled"
        # 还在队列里:直接落终态
        async with self.session_factory() as db:
            run = await db.get(Run, run_id)
            run.status = "canceled"
            run.finished_at = now_utc()
            await db.commit()
            await self.emit_event(run.id, "run_canceled", self._run_brief(run))
        return "canceled"

    # ============ 工作循环 ============

    async def _worker(self, idx: int) -> None:
        while not self._stopping:
            try:
                run_id = await self.queue.dequeue()
            except asyncio.CancelledError:
                return
            task = asyncio.create_task(self._execute_run(run_id))
            self._tasks[run_id] = task

    async def _execute_run(self, run_id: int) -> None:
        try:
            try:
                async with self.session_factory() as db:
                    # 防御性重试:入队侧极端情况下提交略晚于取活
                    run = None
                    for _ in range(5):
                        run = await db.get(Run, run_id)
                        if run is not None and run.status == "queued":
                            break
                        await asyncio.sleep(0.05)
                    if run is None or run.status != "queued":
                        return  # 已被取消或重复出队
                    kind = run.kind
                    executor = self.executors.get(kind)
                    secrets = self._secrets.pop(run_id, RunSecrets())
                    if executor is None:
                        await self._fail_run(run_id, "NO_EXECUTOR",
                                             f"未注册的运行类型: {kind}")
                        return

                    run.status = "running"
                    run.started_at = now_utc()
                    await db.commit()
                    await self.emit_event(run_id, "run_started", self._run_brief(run))

                    ctx = RunContext(db=db, run=run, orchestrator=self, secrets=secrets)
                    result = await executor.execute(ctx)
            except asyncio.CancelledError:
                await self._finish_run(run_id, "canceled")
                raise
            except errors.NovaError as e:
                await self._fail_run(run_id, e.code, e.message)
                return
            except Exception as e:  # noqa: BLE001 — 执行器兜底
                log.exception("执行器异常 run=%s", run_id)
                await self._fail_run(run_id, "EXECUTOR_ERROR", str(e)[:500])
                return
            await self._finish_run(run_id, "completed", result=result)
        finally:
            self._tasks.pop(run_id, None)
            ev = self._done.pop(run_id, None)
            if ev is not None:
                ev.set()

    async def _finish_run(self, run_id: int, status: str,
                          result: dict | None = None) -> None:
        """终态落库:一律用全新会话(执行器会话可能已被异常污染),带重试。"""
        for attempt in range(3):
            try:
                async with self.session_factory() as db:
                    run = await db.get(Run, run_id)
                    if run is None or self.is_terminal(run.status):
                        return
                    run.status = status
                    run.finished_at = now_utc()
                    if result is not None:
                        run.result = result
                        if isinstance(result.get("best_objective"), (int, float)):
                            run.best_objective = result["best_objective"]
                    await db.commit()
                    event = ("run_completed" if status == "completed"
                             else f"run_{status}")
                    await self.emit_event(run_id, event, self._run_brief(run))
                    if status == "completed":
                        # 自动提交失败绝不影响运行终态(已提交),只记告警
                        try:
                            await self._auto_submit(db, run)
                            await db.commit()
                        except Exception:  # noqa: BLE001 — 提交失败仅告警
                            await db.rollback()
                            log.warning("自动提交失败 run=%s", run_id, exc_info=True)
                    return
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — DB 抖动重试
                log.warning("终态落库失败 run=%s status=%s(第 %s 次)",
                            run_id, status, attempt + 1, exc_info=True)
                await asyncio.sleep(0.2 * (attempt + 1))
        log.critical("运行 %s 终态 %s 无法落库(重试耗尽)", run_id, status)

    async def _auto_submit(self, db: AsyncSession, run: Run) -> None:
        await auto_submit_run(db, self.settings, run,
                              emit=lambda t, d: self.emit_event(run.id, t, d))

    async def _fail_run(self, run_id: int, code: str, message: str) -> None:
        for attempt in range(3):
            try:
                async with self.session_factory() as db:
                    run = await db.get(Run, run_id)
                    if run is None or self.is_terminal(run.status):
                        return
                    run.status = "failed"
                    run.error_code = code
                    run.error_message = message
                    run.finished_at = now_utc()
                    await db.commit()
                    await self.emit_event(run_id, "run_failed",
                                          {**self._run_brief(run),
                                           "error_code": code,
                                           "error_message": message})
                    return
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — DB 抖动重试
                log.warning("失败状态落库异常 run=%s(第 %s 次)",
                            run_id, attempt + 1, exc_info=True)
                await asyncio.sleep(0.2 * (attempt + 1))
        log.critical("运行 %s 失败状态无法落库: %s %s", run_id, code, message)
