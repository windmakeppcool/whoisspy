"""MatchRunner：单局单写者（支柱 4）。

职责边界（D24）：engine 只做「跑一局」的通用事情——

1. 步进循环（``next_step`` → 步内流程 → ``check_winner``）；
2. 事件写入：可见性由插件标注 → append（seq 单调）→ ``apply`` 归约；
3. agent 调用与容错链（重试/修复/中性兜底）、prompt 六层拼装、记忆投影；
4. 单写者与终止语义（finished / stopped）。

**具体游戏规则不在这里**：每一步问谁、怎么结算、写哪些事件，全部由游戏插件经
``GameDefinition.play(ctx, step)`` 实现（engine 通过 ``StepContext`` 暴露 IO 原语）。
"""

from __future__ import annotations

import asyncio
import logging
from random import Random
from typing import Any, Protocol

from app.agents.protocol import build_user_prompt
from app.core import ActionRequest, BoardSpec, Event, GameResult, VisMeta
from app.engine.context import EngineStepContext
from app.engine.faults import fallback_action
from app.games.base import GameDefinition, GameState, Step

log = logging.getLogger(__name__)

STEP_TIME_LIMIT_S = 300.0  # 步级总时限兜底
MAX_STEPS = 500  # 单局步数上限（状态机停摆保护）


class _Repo(Protocol):
    async def append_event(self, match_id: int, event: Event) -> Event: ...
    async def update_match(self, match_id: int, *, status: str,
                           result: dict[str, Any] | None = None) -> None: ...
    async def set_seat_roles(self, match_id: int, roles: dict[int, str]) -> None: ...


class _Gateway(Protocol):
    async def ask_json(self, *, base_url: str, api_key: str, model: str,
                       messages: list[dict[str, str]], purpose: str,
                       match_id: int = 0, price_in: float = 0.0, price_out: float = 0.0,
                       price_cached_in: float | None = None) -> dict[str, Any]: ...


class MatchRunner:
    """驱动一局：created → started → 步循环 → finished/stopped。独占事件写入。"""

    def __init__(self, *, match_id: int, game: GameDefinition, spec: BoardSpec,
                 repo: _Repo, gateway: _Gateway, seed: int,
                 seat_meta: dict[int, dict[str, Any]] | None = None,
                 stop_flag: asyncio.Event | None = None,
                 board_id: str = ""):
        self._mid = match_id
        self._game = game
        self._spec = spec
        self._seed = seed
        self._board_id = board_id
        self._repo = repo
        self._gw = gateway
        self._rng = Random(seed)
        self._seat_meta = seat_meta or {}
        self._stop = stop_flag or asyncio.Event()
        self._state: GameState | None = None
        self._day = 1
        self._phase = ""
        self._events: list[Event] = []  # 本局全量事件（带 vis），记忆投影的原料
        self._warned_no_neutral = False  # 插件缺 neutral_action 只告警一次

    # ---- 事件写出（单写者入口） ----

    async def _emit(self, etype: str, payload: dict[str, Any],
                    vis: VisMeta | None = None) -> Event:
        ev = Event(type=etype, payload=payload, day_index=self._day,
                   phase=self._phase, vis=vis or VisMeta(level="public"))
        # 可见性由游戏插件标注（唯一权威），再入库
        if self._state is not None and hasattr(self._game, "visibility"):
            ev.vis = self._game.visibility(ev, self._state)
        ev = await self._repo.append_event(self._mid, ev)
        self._events.append(ev)
        # Reducer：入库后立即归约到状态（支柱 1）
        self._game.apply(self._state, ev)
        return ev

    # ---- agent 调用 ----

    def _seat_cfg(self, seat: int) -> dict[str, Any]:
        return self._seat_meta.get(seat, {})

    def _rule_partition(self, step: Step) -> tuple[dict[str, str], dict[str, str]]:
        """规则切片按缓存语义拆分：(稳定前缀, 本步易变)。

        稳定段取与步骤无关的基线切片（slices_for(空 step)），其余归本步易变段——
        后者随步骤切换而变，只能放在记忆层之后（build_user_prompt 负责落位）。
        """
        all_slices = self._game.rule_slices()
        base_keys = list(self._game.slices_for(Step(kind="")))
        base_set = set(base_keys)
        stable = {k: all_slices[k] for k in base_keys if k in all_slices}
        volatile = {k: all_slices[k] for k in self._game.slices_for(step)
                    if k not in base_set and k in all_slices}
        return stable, volatile

    async def _ask(self, seat: int, request: ActionRequest,
                   purpose: str, step: Step) -> tuple[dict[str, Any] | None, dict[str, Any], bool]:
        """向座位 agent 请求。返回 (action, response, fell_back)。

        step 决定注入哪些规则切片（D12）；purpose 只用于计量与日志，两者不可互推。
        """
        cfg = self._seat_cfg(seat)
        identity = f"你是 {seat} 号座位。"
        if cfg.get("role"):
            identity += f"你的角色：{cfg['role']}。"
        memory = "\n".join(self._memory_items(seat))
        stable, volatile = self._rule_partition(step)
        messages = [{"role": "user", "content": build_user_prompt(
            rule_slices=stable, step_slices=volatile, identity=identity,
            style=cfg.get("style", ""), strategy=cfg.get("strategy", ""),
            memory=memory, request=request)}]
        try:
            resp = await self._gw.ask_json(
                base_url=cfg.get("base_url", ""), api_key=cfg.get("api_key", ""),
                model=cfg.get("model", "mock"), messages=messages, purpose=purpose,
                match_id=self._mid,
                price_in=float(cfg.get("price_per_mtok_in", 0.0) or 0.0),
                price_out=float(cfg.get("price_per_mtok_out", 0.0) or 0.0),
                price_cached_in=cfg.get("price_per_mtok_cached_in"))
        except Exception as e:  # 调用失败：兜底，绝不卡死
            log.warning("seat %s 调用失败(%s)，走兜底", seat, e)
            fb = self._safe_neutral(step, request, seat)
            await self._emit("player.fallback",
                             {"seat": seat, "reason": str(e)[:200], "purpose": purpose},
                             vis=VisMeta(level="god"))
            return fb, {"speech": "", "monologue": "", "action": fb}, True

        # 动作校验/兜底属于插件职责：单独 try，避免插件 bug 被误报成「LLM 调用失败」
        raw_action = resp.get("action") if isinstance(resp.get("action"), dict) else None
        try:
            action = (self._neutral_action(step, request) if raw_action is None
                      else self._game.validate_action(self._state, step, seat, raw_action))
        except Exception as e:  # 插件校验崩了：记 plugin.error，绝不静默降级
            log.exception("座位 %s 的插件校验/兜底失败", seat)
            await self._emit("plugin.error",
                             {"seat": seat, "step": step.kind, "purpose": purpose,
                              "reason": str(e)[:200]},
                             vis=VisMeta(level="god"))
            action = self._safe_neutral(step, request, seat)
        return action, resp, False

    def _safe_neutral(self, step: Step, request: ActionRequest, seat: int) -> dict[str, Any]:
        """取插件的中性动作；插件自己崩了就回落通用中性动作并记日志。"""
        try:
            return self._neutral_action(step, request)
        except Exception:
            log.exception("座位 %s 的 neutral_action 失败，回落通用中性动作", seat)
            return fallback_action(request)

    def _neutral_action(self, step: Step, request: ActionRequest) -> dict[str, Any]:
        """该步骤的中性兜底动作（由游戏插件决定，避免兜底替玩家做决定）。

        例：女巫步的 request.action_type 是 save，但「没答上来」绝不能用解药——
        兜底必须由插件给出该步骤真正中性的动作（pass）。
        插件未实现 neutral_action 时回落到「请求类型 + target 0」的通用兜底
        （对「save 型」动作并不中性，因此契约要求插件必须实现它）。
        """
        neutral = getattr(self._game, "neutral_action", None)
        if callable(neutral):
            return neutral(self._state, step)
        if not self._warned_no_neutral:
            self._warned_no_neutral = True
            log.warning("游戏插件 %s 未实现 neutral_action，回落通用兜底；"
                        "这可能在「用药/开枪」类步骤替玩家做决定",
                        type(self._game).__name__)
        return fallback_action(request)

    def _memory_items(self, seat: int) -> list[str]:
        """该座位可见的事件历史投影（docs/agents-and-llm.md 记忆层）。

        遍历本局全量事件，按各事件的 VisMeta 过滤：public 全可见、seat 仅成员、
        god 不可见。自己的发言也保留：调用无状态（每次全新 prompt），
        模型必须靠记忆层记住自己说过什么（言行一致）。
        """
        lines: list[str] = []
        for ev in self._events:
            if not self._visible_to(ev.vis, seat):
                continue
            line = self._memory_line(ev)
            if line:
                lines.append(line)
        return lines

    def _visible_to(self, vis: VisMeta, seat: int) -> bool:
        """该座位是否可见此事件。"""
        if vis.level == "public":
            return True
        if vis.level == "seat":
            return seat in (vis.seats or [])
        return False  # god：仅上帝视角

    def _memory_line(self, ev: Event) -> str | None:
        """单个事件 → 记忆文本行；渲染规则属于游戏插件（engine 不认识游戏事件）。"""
        hook = getattr(self._game, "memory_line", None)
        if callable(hook):
            return hook(ev)
        return None

    # ---- 步内执行（委托给游戏插件） ----

    async def _exec_step(self, step: Step) -> None:
        """把一步交给游戏插件执行；engine 只提供 StepContext 原语。"""
        await self._game.play(EngineStepContext(self, step), step)

    # ---- 主循环 ----

    async def _deal(self) -> None:
        """发牌：写座位角色 + 逐座位发 role.dealt（仅本人可见），并建初始状态。"""
        roles = self._game.deal(self._spec, self._rng)
        role_map = {r.seat: r.role for r in roles}
        await self._repo.set_seat_roles(self._mid, role_map)
        for r in roles:
            await self._emit("role.dealt", {"seat": r.seat, "role": r.role},
                             vis=VisMeta(level="seat", seats=[r.seat]))
        self._state = self._game.initial_state(self._spec, roles)
        for seat, role in role_map.items():
            self._seat_meta.setdefault(seat, {})["role"] = role

    def _phase_day(self, step: Step) -> int:
        """该步骤所属的「第几天」（插件可覆写，缺省用当前状态的天数）。"""
        hook = getattr(self._game, "phase_day", None)
        return hook(self._state, step) if callable(hook) else self._state.day

    async def _run_step(self, step: Step) -> None:
        """发阶段边界事件后执行一步；步级超时只兜底当前步，绝不卡死整局。"""
        self._day = self._phase_day(step)
        self._phase = step.kind
        await self._emit("phase.started", {"phase": step.kind, "day": self._day})
        try:
            await asyncio.wait_for(self._exec_step(step), timeout=STEP_TIME_LIMIT_S)
        except asyncio.TimeoutError:
            log.error("步骤超时(%s)，跳过", step.kind)
            await self._emit("player.fallback", {"reason": "step_timeout", "step": step.kind},
                             vis=VisMeta(level="god"))

    async def run(self) -> GameResult | None:
        """驱动一局。

        返回 GameResult 表示分出胜负（status=finished）；返回 None 表示未分胜负
        （手动终止 / 步数超限 / 状态机停摆，status=stopped，原因写入 match.stopped）。
        """
        await self._repo.update_match(self._mid, status="running")
        await self._emit("match.created",
                         {"board_id": self._board_id, "game_type": self._game.game_type,
                          "ruleset": self._spec.ruleset, "roles": dict(self._spec.roles),
                          "max_days": self._spec.max_days, "rng_seed": self._seed})
        await self._emit("match.started", {"rng_seed": self._seed})
        await self._deal()

        result: GameResult | None = None
        stop_reason: str | None = None
        steps = 0
        while True:
            steps += 1
            if steps > MAX_STEPS:
                stop_reason = f"步数超限保护（>{MAX_STEPS} 步）"
                break
            if self._stop.is_set():
                stop_reason = "对局被手动终止"
                break
            result = self._game.check_winner(self._state)
            if result is not None:
                break
            step = self._game.next_step(self._state)
            if step.kind in ("", "noop"):
                # noop = 状态机没有可执行步骤；插件可能在此前的 next_step 里直接判了胜负
                result = self._game.check_winner(self._state)
                if result is None:
                    stop_reason = "状态机没有后续步骤（对局无法继续）"
                break
            await self._run_step(step)

        if result is not None:
            self._state.winner = result
            await self._emit("match.finished",
                             {"winner": result.winner, "reason": result.reason})
            await self._repo.update_match(
                self._mid, status="finished",
                result={"winner": result.winner, "reason": result.reason})
            return result

        reason = stop_reason or "对局终止"
        await self._emit("match.stopped", {"reason": reason})
        await self._repo.update_match(self._mid, status="stopped",
                                      result={"winner": None, "reason": reason})
        return None
