# -*- coding: utf-8 -*-
"""兼容层:题目/榜单/提交/用户详情(官方契约同形 + 安全修复)。

安全修复(安全报告 §5):
- /api/users/{id} 与其 submissions 强制登录;
- 榜单条目走脱敏投影(昵称+分数,不暴露 role 等管理字段)。
榜单语义:ascend !== false → 越小越好;同分先到先得(tie_break 显式化)。
"""
from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from ...core import errors
from ...db.models import Problem, Run, Submission, User
from ..deps import DbDep, UserDep
from ..v2.auth import user_brief

router = APIRouter(tags=["compat-data"])


def problem_dict(p: Problem, detail: bool = False) -> dict:
    d = {
        "key": p.key, "name": p.name, "ascend": p.ascend,
        "kind": p.kind, "dataset_version": p.dataset_version,
    }
    c = p.contract or {}
    if detail:
        d.update({
            "description": c.get("description", ""),
            "fun_name": c.get("fun_name", ""),
            "fun_args": c.get("fun_args", []),
            "fun_return": c.get("fun_return", ""),
            "fun_notes": c.get("fun_notes", ""),
            "problem_path": c.get("problem_path", ""),
            "train_data": c.get("train_data", ""),
            "train_solution": c.get("train_solution", ""),
            # 每题默认进化参数(管理端写 contract.evolve_defaults,前端进化表单自动预填)
            "evolve_defaults": c.get("evolve_defaults") or {},
        })
    return d


def submission_dict(s: Submission, user: User | None = None) -> dict:
    d = {
        "id": s.id, "problem_key": s.problem_key, "run_id": s.run_id,
        "objective": s.objective, "is_official": s.is_official,
        "detail": s.detail,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "user_id": s.user_id,
    }
    if user is not None:
        d["user"] = {"id": user.id, "display_name": user.display_name or user.username}
    return d


@router.get("/api/problems")
async def list_problems(db: DbDep):
    rows = (await db.scalars(select(Problem).order_by(Problem.key))).all()
    return {"problems": [problem_dict(p) for p in rows]}


@router.get("/api/problems/{key}")
async def get_problem(key: str, db: DbDep):
    p = await db.get(Problem, key)
    if p is None:
        raise errors.not_found("题目", key)
    return problem_dict(p, detail=True)


@router.get("/api/ranking/{key}")
async def ranking(key: str, db: DbDep, limit: int = 100):
    """实时榜单:每用户取最优提交,ascend 定向,同分先到先得。"""
    p = await db.get(Problem, key)
    if p is None:
        raise errors.not_found("题目", key)
    rows = (await db.scalars(
        select(Submission).where(Submission.problem_key == key)
        .order_by(Submission.id)
    )).all()
    users = {u.id: u for u in (await db.scalars(select(User))).all()}
    best: dict[int, Submission] = {}
    for s in rows:  # 同分先到先得:按提交顺序只替换严格更优的
        cur = best.get(s.user_id)
        if cur is None or _better(s.objective, cur.objective, p.ascend):
            best[s.user_id] = s
    ordered = sorted(
        best.values(),
        key=lambda s: (s.objective if p.ascend else -s.objective, s.id),
    )[: min(limit, 500)]
    return {"entries": [
        {"rank": i + 1, "user_id": s.user_id,
         "username": users[s.user_id].username if s.user_id in users else "",
         "display_name": (users[s.user_id].display_name or
                          (users[s.user_id].username if s.user_id in users else ""))
                         if s.user_id in users else "",
         "best_objective": s.objective, "submission_id": s.id,
         "created_at": s.created_at.isoformat() if s.created_at else None}
        for i, s in enumerate(ordered)
    ], "ascend": p.ascend}


@router.get("/api/ranking/me")
async def ranking_me(db: DbDep, user: UserDep):
    rows = (await db.scalars(
        select(Submission).where(Submission.user_id == user.id)
        .order_by(Submission.id)
    )).all()
    problems = {p.key: p for p in (await db.scalars(select(Problem))).all()}
    entries = []
    for key, p in problems.items():
        mine = [s for s in rows if s.problem_key == key]
        if not mine:
            continue
        best = mine[0]
        for s in mine[1:]:
            if _better(s.objective, best.objective, p.ascend):
                best = s
        rank_row = await _rank_of(db, p, best)
        entries.append({"problem_key": key, "rank": rank_row,
                        "best_objective": best.objective,
                        "submission_id": best.id})
    return {"entries": entries}


async def _rank_of(db, problem: Problem, target: Submission) -> int:
    rows = (await db.scalars(
        select(Submission).where(Submission.problem_key == problem.key)
        .order_by(Submission.id))).all()
    best: dict[int, Submission] = {}
    for s in rows:
        cur = best.get(s.user_id)
        if cur is None or _better(s.objective, cur.objective, problem.ascend):
            best[s.user_id] = s
    ordered = sorted(best.values(),
                     key=lambda s: (s.objective if problem.ascend else -s.objective, s.id))
    for i, s in enumerate(ordered):
        if s.id == target.id:
            return i + 1
    return 0


def _better(candidate: float, incumbent: float, ascend: bool) -> bool:
    return candidate < incumbent if ascend else candidate > incumbent


@router.get("/api/submissions/recent")
async def recent_submissions(db: DbDep, limit: int = 50):
    rows = (await db.scalars(
        select(Submission).order_by(Submission.id.desc())
        .limit(min(limit, 300)))).all()
    users = {u.id: u for u in (await db.scalars(select(User))).all()}
    return {"submissions": [
        submission_dict(s, users.get(s.user_id)) for s in rows
    ]}


@router.get("/api/submissions/my")
async def my_submissions(db: DbDep, user: UserDep, limit: int = 100):
    rows = (await db.scalars(
        select(Submission).where(Submission.user_id == user.id)
        .order_by(Submission.id.desc()).limit(min(limit, 500)))).all()
    return {"submissions": [submission_dict(s, user) for s in rows]}


@router.get("/api/submissions/{submission_id}")
async def get_submission(submission_id: int, db: DbDep, user: UserDep):
    s = await db.get(Submission, submission_id)
    if s is None:
        raise errors.not_found("提交", submission_id)
    u = await db.get(User, s.user_id)
    d = submission_dict(s, u)
    d["result"] = s.detail.get("result")
    return d


@router.get("/api/submissions/{submission_id}/record")
async def submission_record(submission_id: int, db: DbDep, user: UserDep):
    """提交存档(NOVA 对比页/曲线页读取;含 instance.config 的 ascend 等)。"""
    s = await db.get(Submission, submission_id)
    if s is None:
        raise errors.not_found("提交", submission_id)
    u = await db.get(User, s.user_id)
    run = await db.get(Run, s.run_id) if s.run_id else None
    instance = s.detail.get("instance") or {}
    if run is not None and "config" not in instance:
        instance = {"config": {"ascend": run.config.get("ascend", True),
                               "problem_key": run.problem_key,
                               "num_generations": run.total_generations}}
    return {**submission_dict(s, u), "instance": instance,
            "generations": s.detail.get("generations", [])}


@router.get("/api/users/{user_id}")
async def get_user(user_id: int, db: DbDep, user: UserDep):
    """用户详情(强制登录 —— 安全报告 §5 修复)。"""
    target = await db.get(User, user_id)
    if target is None:
        raise errors.not_found("用户", user_id)
    return {**user_brief(target), "profile": {
        k: v for k, v in (target.profile or {}).items() if k in ("email", "avatar")
    }}


@router.get("/api/users/{user_id}/submissions")
async def user_submissions(user_id: int, db: DbDep, user: UserDep,
                           limit: int = 100):
    """他人提交轨迹(强制登录 —— 安全报告 §5 修复)。"""
    target = await db.get(User, user_id)
    if target is None:
        raise errors.not_found("用户", user_id)
    rows = (await db.scalars(
        select(Submission).where(Submission.user_id == user_id)
        .order_by(Submission.id.desc()).limit(min(limit, 500)))).all()
    return {"submissions": [submission_dict(s, target) for s in rows]}
