# -*- coding: utf-8 -*-
"""请求模型(pydantic v2)。响应一律为普通 dict(naive UTC ISO 时间字符串)。"""
from __future__ import annotations

from pydantic import BaseModel, Field


# ============ v2 认证 ============

class RegisterIn(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(default="", max_length=128)


class LoginIn(BaseModel):
    username: str
    password: str


class RefreshIn(BaseModel):
    refresh_token: str


# ============ v2 运行 ============

class RunIn(BaseModel):
    """统一运行入口。kind 决定执行器;game 类题目走 arena 专用端点。"""
    kind: str = Field(default="", description="evolve_official|evolve_local|grind|abtest;留空按模式选择")
    problem_key: str | None = None
    problem_kind: str | None = None
    config: dict = Field(default_factory=dict)
    priority: int = 0
    total_generations: int = 0
    seed_id: int | None = None
    secrets: dict = Field(default_factory=dict,
                          description="llm_api_key 等敏感参数,不落库用后即弃")


class CancelIn(BaseModel):
    reason: str = ""


# ============ v2 种子/收割/实验 ============

class SeedIn(BaseModel):
    problem_key: str
    algorithm: str
    concept: str = ""
    feature: list = Field(default_factory=list)
    objective: float | None = None


class HarvestIn(BaseModel):
    force: bool = False


class AbTestIn(BaseModel):
    problem_key: str
    arms: list[dict] = Field(min_length=2, description="[{name, framework_code|template, seed_id?}]")
    num_generations: int = 5
    llm_model: str | None = None
    child_kind: str = ""
    secrets: dict = Field(default_factory=dict)


class GrindIn(BaseModel):
    items: list[dict] = Field(min_length=1,
                              description="[{problem_key, template|framework_code, seed_id?, num_generations, auto_harvest?}]")
    batch_size: int = 3
    child_kind: str = ""
    secrets: dict = Field(default_factory=dict)


# ============ v2 数据集 ============

class DatasetIn(BaseModel):
    version: str
    content_b64: str
    meta: dict = Field(default_factory=dict)


# ============ v2 Arena ============

class BotIn(BaseModel):
    arena_key: str
    name: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=1, max_length=200_000)
    lang: str = "python"


class MatchIn(BaseModel):
    arena_key: str
    bot_ids: list[int] = Field(min_length=2)
    config: dict = Field(default_factory=dict)


# ============ v2 管理 ============

class QueuePauseIn(BaseModel):
    paused: bool
    reason: str = ""
    resume_at: str = ""


class PrescreenIn(BaseModel):
    problem_key: str
    candidate_code: str
    instance: dict = Field(default_factory=dict, description="合成迷你实例")
    solution: dict | None = None
    timeout_seconds: float = 10.0


# ============ 兼容层(standalone 模式) ============

class CompatEvolutionStartIn(BaseModel):
    """/api/evolution/start 载荷(与官方契约同形,允许未知字段)。"""
    model_config = {"extra": "allow"}

    problem_key: str
    num_generations: int = 5
    framework_type: str = "builtin"
    ascend: bool = True
    llm_model: str | None = None
    llm_base_url: str | None = None
    use_local_llm: bool = True
    framework_code: str | None = None
    framework_filename: str | None = None
    fun_name: str | None = None
    # 官方契约里这两个是数组(如 ["take_item"]);宽容接受数组或字符串
    fun_args: list | str | None = None
    fun_return: list | str | None = None
    fun_notes: str | None = None
    problem_path: str | None = None
    train_data: str | None = None
    train_solution: str | None = None
