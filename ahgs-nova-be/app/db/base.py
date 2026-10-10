# -*- coding: utf-8 -*-
"""SQLAlchemy 2 声明式基类与通用类型。"""
from __future__ import annotations

from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase

# JSONB on Postgres / JSON elsewhere(SQLite 开发库兼容)
JSONType = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass
