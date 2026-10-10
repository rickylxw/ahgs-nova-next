# -*- coding: utf-8 -*-
"""本地进化引擎(standalone 模式的核心执行器):LLM 变异 → 预筛 → 评测 → 选择。

不依赖官方平台。题目契约(problems.contract.evaluate)自带可信裁判:
    {"entry": "solve",                       # 候选须实现的入口
     "entry_doc": "def solve(instance, config) -> ...",  # 展示给 LLM 的签名说明
     "instance": {...},                      # 评测实例
     "prescreen_instance": {...},            # 可选:迷你预筛实例
     "judge": "<python 源码>",               # judge_entry(instance, solution, config) -> objective
     "judge_entry": "judge", "timeout": 10, "description": "..."}

循环(冲榜工作流的平台化,见 ../冲榜实验记录.md 机制 #3/#5/#10):
每代取精英 → LLM 逐个生成变异体 → 预筛秒杀坏候选(失败原因喂回下一代提示词)
→ 全量评测 → 方向感知选择 + 目标值去重。产物与官方 results 同构,收割/棘轮直用。
"""
from __future__ import annotations

import json
import logging
import re

from ...core import errors
from ..llm import LLMError, LLMRequest
from ..evaluators import evaluate_solution
from .base import RunContext, RunExecutor

log = logging.getLogger("nova.exec.evolve")

# 与题目契约裁判约定的罚值一致(违规候选 objective)
PENALTY = 10 ** 9

_FENCE_RE = re.compile(r"```(?:python|py)?\s*(.*?)```", re.DOTALL)
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def extract_code(text: str, entry: str) -> str:
    """从 LLM 应答中提取代码:优先 ```python 围栏;裸文本须含入口函数。

    qwen3 等思考模型经 Ollama 返回时会把 <think>…</think> 混在正文里,先剥除。
    """
    text = _THINK_RE.sub("", text or "")
    blocks = _FENCE_RE.findall(text)
    for block in blocks:
        if f"def {entry}" in block:
            return block.strip()
    if blocks:
        return blocks[0].strip()
    text = (text or "").strip()
    if f"def {entry}" in text:
        return text
    raise ValueError(f"应答中未找到包含 def {entry} 的代码")


def _better(candidate: float, incumbent: float | None, ascend: bool) -> bool:
    if incumbent is None:
        return True
    return candidate < incumbent if ascend else candidate > incumbent


class EvolveEngineExecutor(RunExecutor):
    kind = "evolve_llm"

    def __init__(self, llm_call_budget: int = 200):
        self.llm_call_budget = llm_call_budget

    async def execute(self, ctx: RunContext) -> dict:
        from ...db.models import Problem, Seed

        run = ctx.run
        problem = await ctx.db.get(Problem, run.problem_key)
        if problem is None:
            raise errors.not_found("题目", run.problem_key)
        spec = (problem.contract or {}).get("evaluate") or {}
        entry = spec.get("entry", "solve")
        instance = spec.get("instance")
        judge_source = spec.get("judge", "")
        timeout = float(spec.get("timeout") or ctx.settings.eval_timeout_seconds)
        if not instance or not judge_source.strip():
            raise errors.invalid_input(
                "题目契约缺少 evaluate.instance / evaluate.judge,"
                "本地引擎无法评测该题",
                detail={"problem_key": run.problem_key})

        cfg = run.config or {}
        gens = max(1, int(cfg.get("num_generations") or 5))
        pop_cap = max(2, int(cfg.get("population_size") or 6))
        cands_per_gen = max(1, int(cfg.get("candidates_per_gen") or 3))
        ascend = bool(cfg.get("ascend", problem.ascend))

        seed_code = cfg.get("seed_code") or ""
        if not seed_code and cfg.get("seed_id"):
            seed = await ctx.db.get(Seed, int(cfg["seed_id"]))
            if seed is not None:
                seed_code = seed.algorithm
        seed_concept = cfg.get("seed_concept") or "seed"

        feedback: list[str] = []
        population: list[dict] = []      # {code, objective, concept, generation}
        llm_calls = eval_ok = eval_fail = 0

        # 种子先行:种子失败不致命(允许纯 LLM 起步),但通常种子即下界
        if seed_code.strip():
            outcome = await evaluate_solution(
                seed_code, entry=entry, instance=instance,
                config=cfg.get("eval_config") or {}, judge_source=judge_source,
                judge_entry=spec.get("judge_entry", "judge"), timeout=timeout)
            if outcome.ok:
                population.append({"code": seed_code,
                                   "objective": outcome.objective,
                                   "concept": seed_concept, "generation": 0})
            else:
                feedback.append(f"seed {outcome.fail_reason}: {outcome.detail[:160]}")

        for g in range(1, gens + 1):
            elites = self._elites(population, ascend)
            new_codes: list[tuple[str, str]] = []   # (code, concept)
            for _ in range(cands_per_gen):
                if llm_calls >= self.llm_call_budget:
                    break
                try:
                    code, used = await self._gen_candidate(
                        ctx, problem, entry, spec, ascend, elites, feedback, cfg)
                except LLMError as e:
                    feedback.append(f"llm {e.code}: {e.message[:160]}")
                    await ctx.db.commit()
                    continue
                llm_calls += used
                if code is None:
                    feedback.append(f"gen{g} parse: 候选经 {used} 次生成"
                                    f"(含修复回路)仍无法提取入口函数")
                    await ctx.db.commit()
                    continue
                new_codes.append((code, f"gen{g} llm"))
                await ctx.db.commit()

            for code, concept in new_codes:
                outcome = await self._evaluate(ctx, spec, code, cfg, timeout)
                if outcome.ok:
                    eval_ok += 1
                    population.append({"code": code,
                                       "objective": outcome.objective,
                                       "concept": concept, "generation": g})
                else:
                    eval_fail += 1
                    feedback.append(f"gen{g} {outcome.fail_reason}: "
                                    f"{outcome.detail[:160]}")

            population = self._select(population, ascend, pop_cap)
            # 代末快照:第 1 代即包含种子与首轮候选,不再出现空首屏
            await ctx.set_generation(g, self._best(population, ascend),
                                     {"individuals": [self._brief(p, i) for i, p in
                                                      enumerate(population)],
                                      "feedback": feedback[:]})
            await ctx.emit("gen_stats", {
                "generation": g, "llm_calls": llm_calls,
                "eval_ok": eval_ok, "eval_fail": eval_fail,
                "population": len(population)})

        best = self._best_individual(population, ascend)
        if best is None:
            raise errors.NovaError("NO_CANDIDATES",
                                   "整轮进化没有任何合法候选(种子缺失或全部被淘汰)",
                                   status=502,
                                   detail={"feedback": feedback[:10]})
        return {
            "best_objective": best["objective"],
            "best_heuristic": {
                "algorithm": best["code"], "concept": best["concept"],
                "feature": [], "generation": best["generation"],
            },
            "stats": {"llm_calls": llm_calls, "eval_ok": eval_ok,
                      "eval_fail": eval_fail, "generations": gens,
                      "population": len(population),
                      "feedback": feedback[:10]},
        }

    # ---- 组件 ----

    @staticmethod
    async def _evaluate(ctx: RunContext, spec: dict, code: str, cfg: dict,
                        timeout: float):
        common = dict(entry=spec.get("entry") or None,
                      config=cfg.get("eval_config") or {},
                      judge_source=spec.get("judge", ""),
                      judge_entry=spec.get("judge_entry", "judge"))
        # 预筛(冲榜机制 #3):迷你实例秒杀崩溃/超时候选,省一次全量评测
        pre = spec.get("prescreen_instance")
        if pre:
            quick = await evaluate_solution(code, instance=pre,
                                            timeout=min(timeout, 5.0), **common)
            if not quick.ok:
                quick.detail = "[prescreen] " + quick.detail
                return quick
        return await evaluate_solution(code, instance=spec.get("instance"),
                                       timeout=timeout, **common)

    @staticmethod
    def _elites(population: list[dict], ascend: bool, k: int | None = None) -> list[dict]:
        if not population:
            return []
        ordered = sorted(population,
                         key=lambda p: p["objective"] if ascend else -p["objective"])
        return ordered[:k] if k else ordered[: max(1, len(ordered) // 2)]

    @classmethod
    def _best(cls, population: list[dict], ascend: bool) -> float | None:
        best = cls._best_individual(population, ascend)
        return best["objective"] if best else None

    @staticmethod
    def _best_individual(population: list[dict], ascend: bool) -> dict | None:
        if not population:
            return None
        return (min if ascend else max)(population, key=lambda p: p["objective"])

    @staticmethod
    def _select(population: list[dict], ascend: bool, cap: int) -> list[dict]:
        """不可行淘汰(裁判罚值个体不入种群 —— 平台语义:inf 不上榜)
        + 方向感知截断 + 目标值去重(同分只保留先到者,机制 #5)。"""
        feasible = [p for p in population
                    if p["objective"] is not None and abs(p["objective"]) < PENALTY]
        ordered = sorted(feasible,
                         key=lambda p: p["objective"] if ascend else -p["objective"])
        seen: set[float] = set()
        kept = []
        for p in ordered:
            if p["objective"] in seen:
                continue
            seen.add(p["objective"])
            kept.append(p)
        return kept[:cap]

    @staticmethod
    def _brief(p: dict, idx: int) -> dict:
        return {"id": f"g{p['generation']}-{idx}",
                "objective": p["objective"], "concept": p["concept"],
                "generation": p["generation"],
                "code": p["code"][:8000]}

    async def _gen_candidate(self, ctx: RunContext, problem, entry: str, spec: dict,
                             ascend: bool, elites: list[dict], feedback: list[str],
                             cfg: dict) -> tuple[str | None, int]:
        """生成并提取一个候选;解析失败按 llm_repair_attempts(默认 1)次修复回路重试
        (冲榜机制 #15:失败原因 + 原始输出喂回下次生成)。

        返回 (code|None, 实际 LLM 调用次数)。
        """
        repair = max(0, int(cfg.get("llm_repair_attempts", 1)))
        local_feedback = list(feedback[-5:])
        used = 0
        for attempt in range(repair + 1):
            text = await self._ask_llm(ctx, problem, entry, spec, ascend,
                                       elites, local_feedback, cfg)
            used += 1
            try:
                return extract_code(text, entry), used
            except ValueError as e:
                if attempt >= repair:
                    return None, used
                snippet = text.strip()[:150]
                local_feedback.append(
                    f"上次应答无法提取入口函数 {entry}({e});"
                    f"应答开头:{snippet!r}。直接输出一个只含入口函数的完整 Python 代码块。")
        return None, used  # 不可达(repair+1 次循环内必然 return)

    async def _ask_llm(self, ctx: RunContext, problem, entry: str, spec: dict,
                       ascend: bool, elites: list[dict], feedback: list[str],
                       cfg: dict) -> str:
        cfg_eval = spec or {}
        parts = []
        # 用户经 /api/evolution/{id}/prompt 注入的自定义指令置顶
        if cfg.get("llm_prompt_override"):
            parts.append(str(cfg["llm_prompt_override"]))
        parts.append("你是启发式算法优化专家。请改进以下启发式程序。")
        parts.append(
            f"题目:{problem.name}({problem.key})"
            + (f":{cfg_eval.get('description')}" if cfg_eval.get("description") else ""))
        parts.append(
            f"入口约定:{cfg_eval.get('entry_doc') or f'def {entry}(instance, config) -> 解'}")
        parts.append("评分方向:" + ("目标值越小越好。" if ascend else "目标值越大越好。"))
        if elites:
            parts.append("当前最优个体(目标值越靠前越优):")
            for i, e in enumerate(elites[:3], 1):
                parts.append(f"--- 个体{i}(objective={e['objective']}) ---\n{e['code']}")
        if feedback:
            parts.append("上一轮失败反馈(务必避免同类问题):\n"
                         + "\n".join(feedback[-5:]))
        parts.append("要求:输出且只输出一个完整 Python 代码块,必须定义入口函数 "
                     f"{entry},参数签名严格遵循上面的入口约定;"
                     "可使用纯标准库;确定性优先(固定种子),禁止全局随机。")
        if cfg.get("llm_prompt_suffix"):
            parts.append(str(cfg["llm_prompt_suffix"]))
        req = LLMRequest(
            messages=[{"role": "user", "content": "\n\n".join(parts)}],
            model=str(cfg.get("llm_model") or "mock"),
            thinking=str(cfg.get("llm_thinking") or "default"),
            timeout=float(cfg.get("llm_timeout") or 120.0),
            max_tokens=int(cfg.get("llm_max_tokens") or 4096),
            temperature=(float(cfg["llm_temperature"])
                         if cfg.get("llm_temperature") is not None else None),
            extra=cfg.get("llm_extra") or {},
        )
        chain = None
        if cfg.get("llm_provider"):
            chain = [(str(cfg["llm_provider"]), str(cfg.get("llm_model") or "mock"))]
        resp = await ctx.orchestrator.llm.chat(
            req, run_id=ctx.run.id, user_id=ctx.run.user_id, db=ctx.db, chain=chain)
        return resp.text
