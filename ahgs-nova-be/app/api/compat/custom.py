# -*- coding: utf-8 -*-
"""兼容层:/api/llm-presets、/api/custom-problems/* 与 Agent 建题。

- llm-presets:由网关降级链生成真实预设(id=模型名,applyPreset 语义);
- custom-problems:上传题面文件 → 注册 kind="custom" 题目(存储承载文件,
  契约暂空 —— 引擎可跑需经 Agent 建题或手工补 evaluate);
- Agent 建题:plan(LLM 出题纲)→ execute(LLM 生成裁判+实例,编译/冒烟
  校验后注册 evaluate 契约)→ runs/{id} 轮询。LLM 走网关降级链。
"""
from __future__ import annotations

import asyncio
import json
import re
import uuid

from fastapi import APIRouter, Request
from sqlalchemy import select

from ...core import errors
from ...core.audit import audit
from ...core.security import now_utc
from ...db.models import Problem
from ..deps import DbDep, UserDep

router = APIRouter(tags=["compat-custom"])

_FENCE_RE = re.compile(r"```(?:json|python)?\s*(.*?)```", re.DOTALL)


def _extract_json(text: str) -> dict:
    """从 LLM 应答提取 JSON 对象:优先围栏,退化到首尾花括号截取。"""
    for block in _FENCE_RE.findall(text or ""):
        try:
            v = json.loads(block)
            if isinstance(v, dict):
                return v
        except ValueError:
            continue
    text = text or ""
    i, j = text.find("{"), text.rfind("}")
    if 0 <= i < j:
        try:
            v = json.loads(text[i:j + 1])
            if isinstance(v, dict):
                return v
        except ValueError:
            pass
    raise ValueError("应答中未找到 JSON 对象")


def _agent_new_id() -> str:
    return uuid.uuid4().hex[:12]


def _agent_key(run_id: str) -> str:
    """前端轮询用纯 id;兼容传入完整存储键。"""
    return run_id if "/" in run_id else f"agent/{run_id}.json"


async def _agent_read(ctx, run_id: str) -> dict:
    key = _agent_key(run_id)
    if not ctx.storage.exists(key):
        raise errors.not_found("Agent 任务", run_id)
    return json.loads(ctx.storage.get(key).decode("utf-8"))


async def _agent_write(ctx, run_id: str, state: dict) -> None:
    ctx.storage.put(_agent_key(run_id),
                    json.dumps(state, ensure_ascii=False).encode("utf-8"))


# ---- LLM 预设(NOVA EvoView/CprobView 下拉框) ----

@router.get("/api/llm-presets")
async def llm_presets(request: Request):
    ctx = request.app.state.ctx
    presets = []
    for adapter, model in ctx.llm.fallback_chain:
        presets.append({"id": model, "name": model, "provider": adapter,
                        "base_url": ""})
    return {"presets": presets}


# ---- 自定义题目:列表 / 上传 / 删除 ----

def _custom_brief(key: str, p: Problem) -> dict:
    c = p.contract or {}
    return {"key": p.key, "name": p.name or key,
            "description": c.get("description", ""),
            "has_engine": bool((c.get("evaluate") or {})),
            "files": c.get("custom_files", []),
            "created_at": p.created_at.isoformat() if p.created_at else None}


@router.get("/api/custom-problems")
async def list_custom(db: DbDep, user: UserDep):
    rows = (await db.scalars(
        select(Problem).where(Problem.kind == "custom")
        .order_by(Problem.key))).all()
    return [_custom_brief(p.key, p) for p in rows]


@router.post("/api/custom-problems/upload")
async def upload_custom(request: Request, db: DbDep, user: UserDep):
    """multipart 上传题面文件(datasets/evaluator/example_heuristic 等)。

    注册 kind="custom" 题目:文件入对象存储,契约暂空 —— 引擎可跑需经
    Agent 建题(Agent 会以 evaluator 为参考生成 evaluate 契约)或手工补。
    """
    ctx = request.app.state.ctx
    form = await request.form()
    # 鸭子类型判断:fastapi.UploadFile 是 starlette 版的子类,isinstance 方向会漏
    files = [f for f in form.values()
             if hasattr(f, "read") and hasattr(f, "filename")]
    if not files:
        raise errors.invalid_input("未收到任何文件")
    key = f"custom-{uuid.uuid4().hex[:10]}"
    stored = []
    for f in files:
        content = await f.read()
        if content:
            safe = f.filename.replace("/", "_").replace("\\", "_") or "file"
            ctx.storage.put(f"custom/{key}/files/{safe}", content)
            stored.append(safe)
    stem = files[0].filename.rsplit(".", 1)[0] if files else key
    problem = Problem(
        key=key, name=stem, kind="custom", ascend=True,
        contract={"description": f"自定义题目(上传于 {now_utc().date()})",
                  "custom_files": stored, "owner_id": user.id},
        created_at=now_utc())
    db.add(problem)
    await audit(db, actor=user.username, action="custom.upload",
                target=f"problem:{key}", detail={"files": stored})
    await db.commit()
    return {"key": key, "name": stem, "files": stored}


@router.get("/api/custom-problems/{key}")
async def get_custom(key: str, db: DbDep, user: UserDep):
    p = await db.get(Problem, key)
    if p is None or p.kind != "custom":
        raise errors.not_found("自定义题目", key)
    return _custom_brief(key, p)


@router.delete("/api/custom-problems/{key}")
async def delete_custom(key: str, request: Request, db: DbDep, user: UserDep):
    p = await db.get(Problem, key)
    if p is None or p.kind != "custom":
        raise errors.not_found("自定义题目", key)
    if (p.contract or {}).get("owner_id") not in (None, user.id) \
            and user.role != "admin":
        raise errors.auth_forbidden("只能删除自己上传的题目")
    ctx = request.app.state.ctx
    for fname in (p.contract or {}).get("custom_files", []):
        ctx.storage.delete(f"custom/{key}/files/{fname}")
    await db.delete(p)
    await audit(db, actor=user.username, action="custom.delete",
                target=f"problem:{key}")
    await db.commit()
    return {"ok": True}


# ---- Agent 建题:plan → execute → runs/{id} ----

@router.post("/api/custom-problems/agent/plan")
async def agent_plan(request: Request, db: DbDep, user: UserDep):
    """LLM 依据名称/描述生成出题纲(入口约定 + 实例设计 + 评分规则)。"""
    ctx = request.app.state.ctx
    body = await request.json()
    name = str(body.get("name") or "").strip()
    if not name:
        raise errors.invalid_input("缺少题目名称")
    description = str(body.get("description") or "")
    source_dir = str(body.get("source_dir") or "")

    prompt = (
        "你是算法竞赛出题专家。请为以下题目设计流式决策题纲,只输出一个 JSON 对象。\n"
        f"题目名称:{name}\n题目描述:{description or '(无)'}\n"
        f"参考资料目录:{source_dir or '(无)'}\n"
        "JSON 字段:entry(入口函数名)、entry_doc(入口函数完整签名与说明,"
        "参数含实例数据)、description(一句话题面)、scoring(评分规则文字描述,"
        "极小化方向)、instance(一个小的评测实例 JSON 对象)。\n"
        "要求:确定性、可自洽判分、实例规模小(n≤30)。")
    from ...services.llm import LLMError, LLMRequest

    try:
        resp = await ctx.llm.chat(
            LLMRequest(messages=[{"role": "user", "content": prompt}],
                       timeout=180.0))
    except LLMError as e:
        raise errors.NovaError(e.code, f"出题纲生成失败: {e.message}", 502)
    try:
        plan = _extract_json(resp.text)
    except ValueError as e:
        raise errors.NovaError("AGENT_BAD_PLAN", f"出题纲解析失败: {e}", 502)

    run_id = _agent_new_id()
    state = {"status": "planned", "plan_id": run_id, "name": name,
             "description": description, "plan": plan,
             "created_at": now_utc().isoformat()}
    await _agent_write(ctx, run_id, state)
    await audit(db, actor=user.username, action="agent.plan",
                target=run_id, detail={"name": name})
    await db.commit()
    return state


@router.post("/api/custom-problems/agent/execute")
async def agent_execute(request: Request, db: DbDep, user: UserDep):
    """依据题纲让 LLM 生成裁判与实例,编译+冒烟校验后注册题目;后台执行。"""
    ctx = request.app.state.ctx
    body = await request.json()
    plan_id = str(body.get("plan_id") or "")
    state = await _agent_read(ctx, plan_id)
    if state.get("status") not in ("planned",):
        raise errors.conflict("AGENT_BAD_STATE",
                              f"题纲状态为 {state.get('status')},无法执行")
    name = str(body.get("name") or state.get("name") or "自定义题目")
    state["status"] = "running"
    state["name"] = name
    await _agent_write(ctx, plan_id, state)

    asyncio.create_task(_agent_execute_task(ctx, plan_id, state, name))
    return {"run_id": plan_id, "id": plan_id, "status": "running"}


async def _agent_execute_task(ctx, run_id: str, state: dict, name: str) -> None:
    from ...services.evaluators import evaluate_solution
    from ...services.llm import LLMError, LLMRequest

    plan = state.get("plan") or {}
    try:
        prompt = (
            "你是算法竞赛出题专家。依据题纲生成判定程序,只输出一个 JSON 对象。\n"
            f"题纲:{json.dumps(plan, ensure_ascii=False)}\n"
            "JSON 字段:\n"
            '  "judge": Python 源码字符串,实现 judge(instance, config, ns) —— '
            "按入口约定流式调用 ns[entry](必须 try/except 包裹,候选违规/异常返回 "
            f"10**9),最后返回极小化 objective;\n"
            '  "instance": 评测实例 JSON 对象(与 entry_doc 参数匹配);\n'
            '  "prescreen_instance": 更小的迷你实例。\n'
            "judge 内可用 numpy;必须确定性。")
        resp = await ctx.llm.chat(
            LLMRequest(messages=[{"role": "user", "content": prompt}],
                       timeout=300.0, max_tokens=4096))
        spec = _extract_json(resp.text)
        judge_src = str(spec.get("judge") or "")
        instance = spec.get("instance") or plan.get("instance") or {}
        prescreen = spec.get("prescreen_instance") or instance
        if not judge_src.strip() or "def judge" not in judge_src:
            raise ValueError("生成的 judge 缺少 def judge")
        compile(judge_src, "judge.py", "exec")

        # 冒烟:喂一个必然抛异常的候选(按题纲入口名命名),judge 必须返回罚值而非崩溃
        entry_name = plan.get("entry") or "solve"
        smoke = await evaluate_solution(
            f"def {entry_name}(*a, **k):\n    raise RuntimeError('smoke')\n",
            judge_source=judge_src, judge_entry="judge",
            entry=entry_name, instance=instance, timeout=15)
        if not smoke.ok or smoke.objective != 10 ** 9:
            raise ValueError(
                f"judge 冒烟未通过(违规候选应得 10**9,实得 {smoke.objective!r} / "
                f"{smoke.fail_reason})")

        problem_key = f"custom-agent-{uuid.uuid4().hex[:8]}"
        async with ctx.session_factory() as db:
            db.add(Problem(
                key=problem_key, name=state.get("name") or "Agent 题目",
                kind="custom", ascend=True,
                contract={"description": plan.get("description", ""),
                          "evaluate": {
                              "entry": plan.get("entry") or "solve",
                              "entry_doc": plan.get("entry_doc", ""),
                              "instance": instance,
                              "prescreen_instance": prescreen,
                              "judge": judge_src, "judge_entry": "judge",
                              "timeout": 10,
                          }, "agent_plan_id": run_id,
                          "owner_id": state.get("owner_id")},
                created_at=now_utc()))
            await db.commit()
        state.update({"status": "completed", "problem_key": problem_key})
    except (LLMError, ValueError) as e:
        state.update({"status": "failed", "error": str(e)[:400]})
    except Exception as e:  # noqa: BLE001 — 后台任务兜底
        state.update({"status": "failed", "error": repr(e)[:400]})
    await _agent_write(ctx, run_id, state)


@router.get("/api/custom-problems/agent/runs/{run_id}")
async def agent_run_status(run_id: str, request: Request, user: UserDep):
    ctx = request.app.state.ctx
    state = await _agent_read(ctx, run_id)
    return {"run_id": run_id, "status": state.get("status"),
            "problem_key": state.get("problem_key"),
            "error": state.get("error"), "plan": state.get("plan")}
