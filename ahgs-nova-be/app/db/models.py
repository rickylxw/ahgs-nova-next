# -*- coding: utf-8 -*-
"""数据模型(计划 §5 核心表 + Arena 扩展)。

扩展性约定(为对战小游戏等未来玩法预留):
- problems.kind 区分题目类型:optimization(进化优化)/ game(对战竞技)。
  kind 的取值只是字符串约定,注册表(app/services/registry.py)负责解释。
- runs.kind 区分工作负载:evolve_official / evolve_local / arena_match / grind。
  执行器按 kind 从注册表分派,新增负载类型不改编排器。
- snapshots/contracts 等结构化内容一律 JSONB,契约演进不迁移表。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, JSONType

# ---- 运行状态机(计划 §4.2) ----
RUN_STATUSES = (
    "queued", "provisioning", "running", "finalizing",
    "completed", "failed", "canceled",
)
TERMINAL_STATUSES = ("completed", "failed", "canceled")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(128), default="")
    role: Mapped[str] = mapped_column(String(16), default="user")  # user|admin
    password_hash: Mapped[str] = mapped_column(String(256))
    profile: Mapped[dict] = mapped_column(JSONType, default=dict)  # avatar/email 等扩展资料
    quota: Mapped[dict] = mapped_column(JSONType, default=dict)   # 每用户配额(预留)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=None)

    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped[User] = relationship(back_populates="refresh_tokens")


class Problem(Base):
    __tablename__ = "problems"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    kind: Mapped[str] = mapped_column(String(24), default="optimization")  # optimization|game|...
    ascend: Mapped[bool] = mapped_column(Boolean, default=True)  # True=越小越好(官方语义)
    contract: Mapped[dict] = mapped_column(JSONType, default=dict)  # 题目契约(fun_name/args/notes/arena 配置等)
    dataset_version: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=None)


class Run(Base):
    """统一工作负载:进化运行、对战比赛、批量棘轮都走这一张表。

    config JSONB 存执行器所需全部参数;执行器按 kind 分派(见 services/executors)。
    """
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    problem_key: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    kind: Mapped[str] = mapped_column(String(24), default="evolve_official", index=True)
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    config: Mapped[dict] = mapped_column(JSONType, default=dict)
    result: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    # official 执行器回填:官方平台侧的 evolution run id / framework id
    official_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    official_framework_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    seed_id: Mapped[int | None] = mapped_column(ForeignKey("seeds.id", ondelete="SET NULL"),
                                                nullable=True)
    parent_run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"),
                                                      nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_generation: Mapped[int] = mapped_column(Integer, default=0)
    total_generations: Mapped[int] = mapped_column(Integer, default=0)
    best_objective: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=None)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Generation(Base):
    """每代全量种群快照(计划痛点 #1:中间代不落库 → 全量落库,CurveView 直读)。"""
    __tablename__ = "generations"
    __table_args__ = (UniqueConstraint("run_id", "generation", name="uq_run_generation"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    generation: Mapped[int] = mapped_column(Integer)
    best_objective: Mapped[float | None] = mapped_column(Float, nullable=True)
    snapshot: Mapped[dict] = mapped_column(JSONType, default=dict)  # 官方 population 原文 / 本地执行器输出
    created_at: Mapped[datetime] = mapped_column(DateTime, default=None)


class Submission(Base):
    __tablename__ = "submissions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    problem_key: Mapped[str] = mapped_column(String(64), index=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id", ondelete="SET NULL"),
                                               nullable=True)
    objective: Mapped[float] = mapped_column(Float, index=True)
    is_official: Mapped[bool] = mapped_column(Boolean, default=True)
    detail: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=None, index=True)


class Seed(Base):
    """种子库(计划 §4.5:Seed Bank)。objective 记录收割时成绩,方向感知守卫据此判定。"""
    __tablename__ = "seeds"

    id: Mapped[int] = mapped_column(primary_key=True)
    problem_key: Mapped[str] = mapped_column(String(64), index=True)
    algorithm: Mapped[str] = mapped_column(Text, default="")        # 启发式源码
    concept: Mapped[str] = mapped_column(Text, default="")
    feature: Mapped[list] = mapped_column(JSONType, default=list)
    objective: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(64), default="manual")  # manual|harvest|import
    source_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    generation: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=None)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=None)


class AbTest(Base):
    __tablename__ = "abtests"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    problem_key: Mapped[str] = mapped_column(String(64), index=True)
    arms: Mapped[list] = mapped_column(JSONType, default=list)   # [{name, run_id, ...}]
    result: Mapped[dict | None] = mapped_column(JSONType, nullable=True)  # 对比报告
    status: Mapped[str] = mapped_column(String(24), default="running")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=None)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class LlmCall(Base):
    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128))
    thinking: Mapped[str] = mapped_column(String(16), default="")   # disabled|low|high
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=None)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor: Mapped[str] = mapped_column(String(128), index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    target: Mapped[str] = mapped_column(String(256), default="")
    detail: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=None)


class Dataset(Base):
    """题目数据集注册中心(计划 §4.6):版本号 + 校验和,对象存储键指向文件。"""
    __tablename__ = "datasets"

    id: Mapped[int] = mapped_column(primary_key=True)
    problem_key: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[str] = mapped_column(String(64))
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    storage_key: Mapped[str] = mapped_column(String(512))
    meta: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=None)


# ============ Arena 扩展(对战小游戏:上传对战程序互打) ============

class Bot(Base):
    """用户上传的对战程序。

    code 为指定 arena 的入口约定源码(如 tictactoe 要求实现 move(board, me));
    执行在受限子进程内进行(见 app/arenas/runtime.py),生产路径为 Docker 沙箱池。
    """
    __tablename__ = "bots"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    arena_key: Mapped[str] = mapped_column(String(64), index=True)  # 对应 ArenaRegistry
    name: Mapped[str] = mapped_column(String(128))
    code: Mapped[str] = mapped_column(Text)
    lang: Mapped[str] = mapped_column(String(16), default="python")
    rating: Mapped[float] = mapped_column(Float, default=1000.0)    # ELO
    wins: Mapped[int] = mapped_column(Integer, default=0)
    losses: Mapped[int] = mapped_column(Integer, default=0)
    draws: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=None)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=None)


class Match(Base):
    """一场对战(可两方或多方循环)。result 由 Arena 实现产出,统一 JSONB。"""
    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"),
                                               nullable=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    arena_key: Mapped[str] = mapped_column(String(64), index=True)
    config: Mapped[dict] = mapped_column(JSONType, default=dict)   # 局数/随机种子等
    bot_ids: Mapped[list] = mapped_column(JSONType, default=list)
    status: Mapped[str] = mapped_column(String(24), default="queued")
    result: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=None)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
