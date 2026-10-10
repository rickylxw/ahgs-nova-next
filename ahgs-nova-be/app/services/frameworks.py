# -*- coding: utf-8 -*-
"""框架模板渲染:把种子(Seed)注入模板,替代本地 build_framework.py 的服务器端最小实现。

模板占位符约定:
    {{PROBLEM_KEY}}      题目 key
    {{SEED_ALGORITHM}}   种子启发式源码
    {{SEED_CONCEPT}}     种子概念说明
    {{SEED_FEATURES}}    种子特征(JSON 文本)
模板可直接内联传入,或先经存储服务上传为 templates/<name> 再按 key 引用。
"""
from __future__ import annotations

import json

from ..core import errors
from .storage import LocalStorage

PLACEHOLDER_SEED_CODE = "algorithm"  # 官方平台框架里种子函数名,见冲榜记录 §7


def render_framework(template: str, *, problem_key: str, seed_code: str = "",
                     seed_concept: str = "", seed_features: list | None = None) -> str:
    out = template
    out = out.replace("{{PROBLEM_KEY}}", problem_key)
    out = out.replace("{{SEED_ALGORITHM}}", seed_code)
    out = out.replace("{{SEED_CONCEPT}}", seed_concept)
    out = out.replace("{{SEED_FEATURES}}", json.dumps(seed_features or [], ensure_ascii=False))
    return out


def load_template(storage: LocalStorage | None, template: str) -> str:
    """template 以 "storage:" 前缀表示存储键(如 storage:templates/v2),否则视为内联文本。"""
    if not template:
        raise errors.invalid_input("模板为空")
    if template.startswith("storage:"):
        if storage is None:
            raise errors.invalid_input("当前配置未启用对象存储")
        key = template[len("storage:"):]
        if not storage.exists(key):
            raise errors.not_found("模板", key)
        return storage.get(key).decode("utf-8")
    return template
