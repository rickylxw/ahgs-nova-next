# -*- coding: utf-8 -*-
"""运行完成自动提交(NOVA_AUTO_SUBMIT)。"""
from __future__ import annotations

import asyncio
import httpx
from sqlalchemy import select

from app.main import create_app

from .conftest import login_admin, make_settings, register_and_login, seed_problem, wait_run


async def _submissions(app):
    from app.db.models import Submission

    async with app.state.ctx.session_factory() as db:
        return (await db.scalars(select(Submission))).all()


async def _run_one(client, user, problem_key, gens=2):
    r = await client.post("/api/v2/run", headers=user, json={
        "kind": "evolve_local", "problem_key": problem_key,
        "config": {"num_generations": gens, "population_size": 4}})
    assert r.status_code == 201, r.text
    return await wait_run(client, user, r.json()["id"])


async def test_auto_submit_on_creates_submission_with_audit(tmp_path):
    """开启开关:完成的 evolve 运行自动创建 Submission(含 detail 形状)+ 审计。"""
    settings = make_settings(tmp_path, auto_submit=True)
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                     base_url="http://t") as c:
            admin = await login_admin(c, settings)
            user = await register_and_login(c, "asub1")
            await seed_problem(c, admin, "asub-p", ascend=True)

            done = await _run_one(c, user, "asub-p")
            assert done["status"] == "completed"

            subs = await _submissions(app)
            assert len(subs) == 1
            sub = subs[0]
            assert sub.run_id == done["id"]
            assert sub.objective == done["best_objective"]
            assert sub.detail["instance"]["config"]["ascend"] is True
            assert "best_heuristic" in sub.detail["result"]

            # 审计日志
            r = await c.get("/api/v2/admin/audit", headers=admin)
            actions = [a["action"] for a in r.json()["audit"]]
            assert "submission.auto" in actions

            # 手动 submit 防重复:返回既有记录,不新增
            r2 = await c.post(f"/api/evolution/{done['id']}/submit", headers=user)
            assert r2.status_code == 200
            assert r2.json()["duplicate"] is True
            assert len(await _submissions(app)) == 1


async def test_auto_submit_off_by_default(tmp_path):
    """默认关:完成不产生提交。"""
    settings = make_settings(tmp_path)  # auto_submit 默认 False
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                     base_url="http://t") as c:
            admin = await login_admin(c, settings)
            user = await register_and_login(c, "asub2")
            await seed_problem(c, admin, "asub-off")

            done = await _run_one(c, user, "asub-off")
            assert done["status"] == "completed"
            assert await _submissions(app) == []


async def test_auto_submit_skips_failed(tmp_path):
    """失败运行不自动提交。"""
    settings = make_settings(tmp_path, auto_submit=True)
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                     base_url="http://t") as c:
            admin = await login_admin(c, settings)
            user = await register_and_login(c, "asub3")
            await seed_problem(c, admin, "asub-fail")

            # LLM 提供商不存在 → 无候选 → 运行失败
            r = await c.post("/api/v2/run", headers=user, json={
                "kind": "evolve_llm", "problem_key": "asub-fail",
                "config": {"num_generations": 1, "candidates_per_gen": 1,
                           "llm_model": "x", "llm_provider": "no-such-provider"}})
            done = await wait_run(c, user, r.json()["id"], timeout=30)
            assert done["status"] == "failed"
            assert await _submissions(app) == []


async def test_manual_submit_then_auto_no_duplicate(tmp_path):
    """手动先提交:自动提交因去重跳过(仍只有一条)。"""
    settings = make_settings(tmp_path, auto_submit=True)
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                     base_url="http://t") as c:
            admin = await login_admin(c, settings)
            user = await register_and_login(c, "asub4")
            await seed_problem(c, admin, "asub-man")

            done = await _run_one(c, user, "asub-man")
            r = await c.post(f"/api/evolution/{done['id']}/submit", headers=user)
            assert r.status_code == 200
            subs = await _submissions(app)
            assert len(subs) == 1
            assert subs[0].run_id == done["id"]


async def test_grind_children_auto_submit(tmp_path):
    """grind 子运行(evolve_local)完成也各自自动提交;父运行(grind)不提交。"""
    settings = make_settings(tmp_path, auto_submit=True)
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                     base_url="http://t") as c:
            admin = await login_admin(c, settings)
            user = await register_and_login(c, "asub5")
            await seed_problem(c, admin, "asub-g1")

            r = await c.post("/api/v2/grind", headers=user, json={
                "items": [{"problem_key": "asub-g1", "num_generations": 1,
                           "population_size": 4}],
                "batch_size": 1, "child_kind": "evolve_local"})
            assert r.status_code == 201, r.text
            done = await wait_run(c, user, r.json()["id"], timeout=30)
            assert done["status"] == "completed", done.get("error_message")

            from app.db.models import Submission
            async with app.state.ctx.session_factory() as db:
                subs = (await db.scalars(select(Submission))).all()
            assert len(subs) == 1
            assert subs[0].run_id != done["id"]  # 是子运行,不是 grind 父运行
