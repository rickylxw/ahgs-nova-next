# -*- coding: utf-8 -*-
"""v2 数据集注册中心(计划 §4.6):版本化入库 + 下载 API(官方缺)。"""
from __future__ import annotations

import base64

from fastapi import APIRouter, Request, Response
from sqlalchemy import select

from ...core import errors
from ...core.audit import audit
from ...core.security import now_utc
from ...db.models import Dataset, Problem
from ...schemas import DatasetIn
from ..deps import AdminDep, DbDep, UserDep

router = APIRouter(tags=["v2-datasets"])


def dataset_dict(d: Dataset) -> dict:
    return {
        "id": d.id, "problem_key": d.problem_key, "version": d.version,
        "sha256": d.sha256, "size_bytes": d.size_bytes, "meta": d.meta,
        "created_at": d.created_at.isoformat() if d.created_at else None,
    }


@router.get("/api/v2/problems/{problem_key}/datasets")
async def list_datasets(problem_key: str, db: DbDep, user: UserDep):
    rows = (await db.scalars(
        select(Dataset).where(Dataset.problem_key == problem_key)
        .order_by(Dataset.id.desc())
    )).all()
    return {"datasets": [dataset_dict(d) for d in rows]}


@router.post("/api/v2/problems/{problem_key}/datasets", status_code=201)
async def upload_dataset(problem_key: str, body: DatasetIn,
                         request: Request, db: DbDep, user: AdminDep):
    """入库数据集(admin;内容 base64,校验和自动计算)。"""
    ctx = request.app.state.ctx
    problem = await db.get(Problem, problem_key)
    if problem is None:
        raise errors.not_found("题目", problem_key)
    try:
        content = base64.b64decode(body.content_b64, validate=True)
    except Exception as e:
        raise errors.invalid_input(f"content_b64 非法: {e}") from e
    if not content:
        raise errors.invalid_input("数据集内容为空")
    version_slug = body.version.replace("/", "_").replace("..", "_")
    key = f"datasets/{problem_key}/{version_slug}"
    sha = ctx.storage.put(key, content)
    row = Dataset(problem_key=problem_key, version=body.version, sha256=sha,
                  size_bytes=len(content), storage_key=key, meta=body.meta,
                  created_at=now_utc())
    problem.dataset_version = body.version
    db.add(row)
    await audit(db, actor=user.username, action="dataset.upload",
                target=f"dataset:{problem_key}@{body.version}")
    await db.commit()
    return dataset_dict(row)


@router.get("/api/v2/datasets/{dataset_id}/download")
async def download_dataset(dataset_id: int, request: Request,
                           db: DbDep, user: UserDep):
    """下载数据集(登录用户;按角色收紧可后续在依赖里做)。"""
    ctx = request.app.state.ctx
    row = await db.get(Dataset, dataset_id)
    if row is None:
        raise errors.not_found("数据集", dataset_id)
    if not ctx.storage.exists(row.storage_key):
        raise errors.NovaError("STORAGE_MISSING", "存储对象缺失", 500)
    content = ctx.storage.get(row.storage_key)
    await audit(db, actor=user.username, action="dataset.download",
                target=f"dataset:{row.id}")
    await db.commit()
    return Response(
        content=content, media_type="application/octet-stream",
        headers={"Content-Disposition":
                 f'attachment; filename="{row.problem_key}_{row.version}"'},
    )
