# -*- coding: utf-8 -*-
"""对战执行器:按 Match 行驱动 Arena 插件跑完整场对阵,并更新 ELO 与战绩。

config: {"match_id": <id>}(Match 行在 API 层创建;run 为其执行载体)
对局事件逐局推送(match_game_end),全程可在 WS 上围观。
"""
from __future__ import annotations

from ...arenas.base import ArenaError
from ...core import errors
from ...core.security import now_utc
from .base import RunContext, RunExecutor


class _BotProgram:
    """Arena 需要的最小 bot 视图(不暴露 ORM 对象给对局运行时)。"""

    def __init__(self, bot):
        self.id = bot.id
        self.name = bot.name
        self.code = bot.code
        self.lang = bot.lang


class ArenaMatchExecutor(RunExecutor):
    kind = "arena_match"

    async def execute(self, ctx: RunContext) -> dict:
        from ...arenas import default_registry
        from ...db.models import Bot, Match

        match_id = int((ctx.run.config or {}).get("match_id") or 0)
        match = await ctx.db.get(Match, match_id)
        if match is None:
            raise errors.not_found("比赛", match_id)
        if match.run_id != ctx.run.id:
            raise errors.invalid_input("match 与 run 不匹配")

        arena = default_registry.get(match.arena_key)
        bots: list[Bot] = []
        for bid in match.bot_ids or []:
            bot = await ctx.db.get(Bot, int(bid))
            if bot is None or not bot.active:
                raise errors.not_found("bot", bid)
            bots.append(bot)

        async def on_game(record) -> None:
            await ctx.emit("match_game_end", record.as_dict())

        try:
            result = await arena.run_match(
                [_BotProgram(b) for b in bots], match.config, on_game,
            )
        except ArenaError as e:
            raise errors.NovaError(f"ARENA_{e.code}", e.message, detail={
                "arena": match.arena_key, "match_id": match.id}) from e

        await self._apply_ratings_and_records(ctx, result)
        match.status = "completed"
        match.finished_at = now_utc()
        match.result = result
        await ctx.db.commit()
        return {"match_id": match.id, "arena": match.arena_key,
                "scores": result.get("scores"), "games": len(result.get("games", []))}

    @staticmethod
    async def _apply_ratings_and_records(ctx: RunContext, result: dict) -> None:
        """逐局 ELO(K=32)+ 战绩累计。

        双人局走 legacy 两两路径;带 ranking 的多人局按名次组一次更新
        (arenas.ratings.apply_ranking,组内并列均分,零和)。
        """
        from ...arenas import ratings
        from ...db.models import Bot

        cache: dict[int, Bot] = {}

        async def bot_of(bid: int) -> Bot | None:
            if bid not in cache:
                cache[bid] = await ctx.db.get(Bot, int(bid))
            return cache[bid]

        for game in result.get("games", []):
            ranking = game.get("ranking")
            if ranking:
                groups = [[int(bid) for bid in g] for g in ranking]
                table: dict[int, float] = {}
                missing = False
                for g in groups:
                    for bid in g:
                        bot = await bot_of(bid)
                        if bot is None:
                            missing = True
                            break
                        table[bid] = bot.rating
                    if missing:
                        break
                if missing:
                    continue
                ratings.apply_ranking(table, groups)
                n_groups = len(groups)
                for gi, g in enumerate(groups):
                    counter = ("wins" if gi == 0
                               else "losses" if gi == n_groups - 1 else "draws")
                    for bid in g:
                        bot = await bot_of(bid)
                        bot.rating = round(table[bid], 2)
                        setattr(bot, counter, getattr(bot, counter) + 1)
                continue

            a_id, b_id = game["players"]
            if a_id == b_id:
                continue
            bot_a, bot_b = await bot_of(a_id), await bot_of(b_id)
            if bot_a is None or bot_b is None:
                continue
            winner = game.get("winner")
            score_a = 0.5 if winner is None else (1.0 if winner == a_id else 0.0)
            ra, rb = ratings.apply_pair(bot_a.rating, bot_b.rating, score_a)
            bot_a.rating, bot_b.rating = round(ra, 2), round(rb, 2)
            if score_a == 1.0:
                bot_a.wins += 1
                bot_b.losses += 1
            elif score_a == 0.0:
                bot_a.losses += 1
                bot_b.wins += 1
            else:
                bot_a.draws += 1
                bot_b.draws += 1
