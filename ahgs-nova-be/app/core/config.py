# -*- coding: utf-8 -*-
"""全局配置(pydantic-settings)。

所有配置可用环境变量或 .env 覆盖;键名见 .env.example。
"""
from __future__ import annotations

import json
from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NOVA_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ---- 数据库 ----
    database_url: str = "sqlite+aiosqlite:///./nova.db"

    # ---- 安全 ----
    jwt_secret: str = "change-me"
    access_token_minutes: int = 120          # 计划 §4.1:JWT ≤ 2h
    refresh_token_days: int = 30
    login_max_failures: int = 5
    lockout_minutes: int = 15
    # NoDecode:禁用 pydantic-settings 的 JSON 自动解码,
    # 让 .env/环境变量里的逗号串走自定义 CSV 校验器
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    admin_username: str = ""
    admin_password: str = ""
    admin_display_name: str = "Nova Admin"

    # ---- 运行编排 ----
    max_concurrent_per_user: int = 20        # 替代官方一刀切 20,可配置
    queue_paused: bool = False               # 显式的"数据保护中"语义(计划 §4.2)
    queue_pause_reason: str = ""
    queue_pause_until: str = ""              # 预告恢复时间(展示用,ISO 文本)
    # 运行完成自动提交(evolve 类运行终态自动创建 Submission;默认关,.env 打开)
    auto_submit: bool = False
    eval_timeout_seconds: float = 30.0
    # 外部 Arena 插件("模块:类" 逗号分隔),为对战小游戏玩法预留
    arena_plugins: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # ---- 存储 ----
    storage_dir: str = "./data/storage"

    # ---- LLM 网关 ----
    llm_fallback_chain: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["mock:mock"])
    llm_platform_keys: Annotated[dict[str, dict], NoDecode] = Field(default_factory=dict)

    @field_validator("cors_origins", "llm_fallback_chain", mode="before")
    @classmethod
    def _split_csv(cls, v):
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        return v

    @field_validator("llm_platform_keys", mode="before")
    @classmethod
    def _parse_json(cls, v):
        if isinstance(v, str):
            return json.loads(v or "{}")
        return v

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgresql")


@lru_cache
def get_settings() -> Settings:
    return Settings()
