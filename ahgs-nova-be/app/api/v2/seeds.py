# -*- coding: utf-8 -*-
"""v2 种子库(Seed Bank,计划 §4.5)。"""
from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import select

from ...core import errors
from ...core.audit import audit
from ...core.security import now_utc
from ...db.models import Problem, Seed
from ...schemas import SeedIn
from ..deps import DbDep, UserDep

router = APIRouter(prefix="/api/v2/seeds", tags=["v2-seeds"])


def seed_dict(s: Seed, include_code: bool = True) -> dict:
    d = {
        "id": s.id, "problem_key": s.problem_key, "concept": s.concept,
        "feature": s.feature, "objective": s.objective, "source": s.source,
        "source_run_id": s.source_run_id, "generation": s.generation,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }
    if include_code:
        d["algorithm"] = s.algorithm
    return d


@router.get("")
async def list_seeds(db: DbDep, user: UserDep, problem_key: str | None = None,
                     limit: int = 100):
    q = select(Seed).order_by(Seed.id.desc()).limit(min(limit, 500))
    if problem_key:
        q = q.where(Seed.problem_key == problem_key)
    rows = (await db.scalars(q)).all()
    return {"seeds": [seed_dict(s, include_code=False) for s in rows]}


@router.get("/{seed_id}")
async def get_seed(seed_id: int, db: DbDep, user: UserDep):
    seed = await db.get(Seed, seed_id)
    if seed is None:
        raise errors.not_found("种子", seed_id)
    return seed_dict(seed)


@router.post("", status_code=201)
async def create_seed(body: SeedIn, request: Request, db: DbDep, user: UserDep):
    """手工导入种子(收割走 /api/v2/harvest/{run_id})。"""
    if await db.get(Problem, body.problem_key) is None:
        raise errors.not_found("题目", body.problem_key)
    seed = Seed(problem_key=body.problem_key, algorithm=body.algorithm,
                concept=body.concept, feature=body.feature,
                objective=body.objective, source="manual",
                created_at=now_utc(), updated_at=now_utc())
    db.add(seed)
    await db.flush()
    await audit(db, actor=user.username, action="seed.create",
                target=f"seed:{seed.id}")
    await db.commit()
    return seed_dict(seed)


@router.delete("/{seed_id}", status_code=204)
async def delete_seed(seed_id: int, request: Request, db: DbDep, user: UserDep):
    """下架种子(管理员;档案只追加原则的例外出口)。"""
    if user.role != "admin":
        raise errors.auth_forbidden("仅管理员可删除种子")
    seed = await db.get(Seed, seed_id)
    if seed is None:
        raise errors.not_found("种子", seed_id)
    await db.delete(seed)
    await audit(db, actor=user.username, action="seed.delete",
                target=f"seed:{seed_id}")
    await db.commit()
