# -*- coding: utf-8 -*-
"""对象存储:本地目录起步,接口按 S3 语义抽象(计划 §3)。

换 S3/MinIO 时实现同一接口即可,数据集/框架/产物存储代码不变。
"""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path


class LocalStorage:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # 防目录穿越:规范化后必须仍在 root 内
        p = (self.root / key).resolve()
        if not str(p).startswith(str(self.root.resolve())):
            raise ValueError(f"非法存储键: {key}")
        return p

    def put(self, key: str, data: bytes) -> str:
        """写入对象,返回 sha256 校验和。"""
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return hashlib.sha256(data).hexdigest()

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def delete(self, key: str) -> None:
        p = self._path(key)
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        elif p.exists():
            p.unlink()
