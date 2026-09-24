"""引擎提供给游戏插件的步内能力（StepContext 的唯一实现）。

engine 只暴露 IO 原语：发事件、问 agent、发言、收票、并发收集。
「谁在这步行动、怎么结算、按什么顺序」全部由游戏插件（games/<name>/flow.py）决定，
engine 不再认识任何具体游戏的角色名、事件名或私有状态键。
"""

from __future__ import annotations

import asyncio
from random import Random
from typing import Any

from app.core import ActionRequest, BoardSpec, Event, VisMeta
from app.games.base import GameState, Step


class EngineStepContext:
    """把 MatchRunner 的能力按原语粒度暴露给插件。"""

    def __init__(self, runner: Any, step: Step) -> None:
        self._runner = runner
        self.step = step

    # ---- 状态与环境 ----

    @property
    def state(self) -> GameState:
        return self._runner._state

    @property
    def spec(self) -> BoardSpec:
        return self._runner._spec

    @property
    def rng(self) -> Random:
        """对局级带种子随机源（插件用它做平票决胜等，结果必须写入事件）。"""
        return self._runner._rng

    # ---- 事件 ----

    async def emit(self, etype: str, payload: dict[str, Any] | None = None,
                   vis: VisMeta | None = None) -> Event:
        """落事件（seq 单写者）+ 立即归约到状态。可见性由插件 visibility() 标注。"""
        return await self._runner._emit(etype, payload or {}, vis)

    async def monologue(self, seat: int, resp: dict[str, Any]) -> None:
        """把这次调用的内心独白落成 god 级事件（D6：每次调用都有独白）。"""
        if resp.get("monologue"):
            await self.emit("player.monologue", {"seat": seat, "text": resp["monologue"]})

    # ---- agent 调用 ----

    async def ask(self, seat: int, request: ActionRequest,
                  purpose: str = "action",
                  step: Step | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
        """向单个座位请求动作；校验/切片按 step（缺省=当前步骤）。

        子步骤（如竞选报名/收刀/开枪）必须显式传自己的 step：动作合法性由
        插件按 step.kind 判定，规则切片也按 step 注入（D12）。
        """
        action, resp, _fell = await self._runner._ask(seat, request, purpose,
                                                      step or self.step)
        return action, resp

    async def ask_many(self, seats: list[int], request: ActionRequest,
                       purpose: str = "action",
                       step: Step | None = None) -> dict[int, tuple[dict[str, Any], dict[str, Any]]]:
        """并行收集多个座位的动作（互不通气，如收刀提案/上警报名）。"""
        out: dict[int, tuple[dict[str, Any], dict[str, Any]]] = {}

        async def one(seat: int) -> None:
            action, resp = await self.ask(seat, request, purpose, step)
            out[seat] = (action, resp)
            await self.monologue(seat, resp)

        await asyncio.gather(*(one(s) for s in seats))
        return out

    async def speech(self, seat: int, request: ActionRequest, *, channel: bool = False,
                     purpose: str = "speech", step: Step | None = None) -> dict[str, Any]:
        """一次发言调用：落发言事件 + 独白（频道发言落 channel.message）。"""
        _action, resp = await self.ask(seat, request, purpose, step)
        await self.emit("channel.message" if channel else "player.speech",
                        {"seat": seat, "text": resp.get("speech", "")})
        await self.monologue(seat, resp)
        return resp

    async def collect_ballot(self, voters: list[int], candidates: list[int], *,
                             title: str = "投票", step_kind: str = "ballot",
                             purpose: str = "vote") -> dict[int, int]:
        """并行收票（防跟票）：逐票落 vote.cast，返回 voter → target。

        计票与平票规则由插件决定（引擎不认识警长 2 票权重）。
        """
        ballot_step = Step(kind=step_kind,
                           params={"candidates": list(candidates), "title": title})
        request = self._runner._game.action_schema(self.state, ballot_step)
        votes: dict[int, int] = {}
        if request is None:
            return votes

        async def one(voter: int) -> None:
            action, resp, _fell = await self._runner._ask(voter, request, purpose, ballot_step)
            target = int(action.get("target") or 0)
            votes[voter] = target
            await self.emit("vote.cast", {"seat": voter, "target": target})
            await self.monologue(voter, resp)

        await asyncio.gather(*(one(v) for v in voters))
        return votes
