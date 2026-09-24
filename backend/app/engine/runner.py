"""MatchRunner：单局单写者（支柱 4）。

步进循环：next_step → 按 kind 执行 Step 原语 → 事件经 visibility 标注 →
append（seq 单调）→ apply 归约。任何 agent 失败走容错链落中性动作。
"""

from __future__ import annotations

import asyncio
import logging
from random import Random
from typing import Any, Protocol

from app.agents.protocol import build_user_prompt, fence_memory
from app.core import ActionRequest, BoardSpec, Event, GameResult, VisMeta
from app.engine.faults import fallback_action
from app.games.base import GameDefinition, GameState, Step

log = logging.getLogger(__name__)

STEP_TIME_LIMIT_S = 300.0  # 步级总时限兜底


class _Repo(Protocol):
    async def append_event(self, match_id: int, event: Event) -> Event: ...
    async def update_match(self, match_id: int, *, status: str,
                           result: dict[str, Any] | None = None) -> None: ...
    async def set_seat_roles(self, match_id: int, roles: dict[int, str]) -> None: ...


class _Gateway(Protocol):
    async def ask_json(self, *, base_url: str, api_key: str, model: str,
                       messages: list[dict[str, str]], purpose: str,
                       match_id: int = 0) -> dict[str, Any]: ...


class MatchRunner:
    """驱动一局：deal → started → 步循环 → finished/stopped。独占事件写入。"""

    def __init__(self, *, match_id: int, game: GameDefinition, spec: BoardSpec | None,
                 repo: _Repo, gateway: _Gateway, seed: int,
                 seat_meta: dict[int, dict[str, Any]] | None = None,
                 stop_flag: asyncio.Event | None = None):
        self._mid = match_id
        self._game = game
        self._spec = spec
        self._repo = repo
        self._gw = gateway
        self._rng = Random(seed)
        self._seat_meta = seat_meta or {}
        self._stop = stop_flag or asyncio.Event()
        self._state: GameState | None = None
        self._day = 1
        self._phase = ""
        self._events: list[Event] = []  # 本局全量事件（带 vis），记忆投影的原料

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

    async def _ask(self, seat: int, request: ActionRequest,
                   purpose: str) -> tuple[dict[str, Any] | None, dict[str, Any], bool]:
        """向座位 agent 请求。返回 (action, response, fell_back)。"""
        cfg = self._seat_cfg(seat)
        identity = f"你是 {seat} 号座位。"
        if cfg.get("role"):
            identity += f"你的角色：{cfg['role']}。"
        memory = "\n".join(self._memory_items(seat))
        rule_slices = {k: self._game.rule_slices()[k]
                       for k in self._game.slices_for(Step(kind="")) if k in self._game.rule_slices()}
        messages = [{"role": "user", "content": build_user_prompt(
            rule_slices=rule_slices, identity=identity,
            style=cfg.get("style", ""), strategy=cfg.get("strategy", ""),
            memory=memory, request=request)}]
        try:
            resp = await self._gw.ask_json(
                base_url=cfg.get("base_url", ""), api_key=cfg.get("api_key", ""),
                model=cfg.get("model", "mock"), messages=messages, purpose=purpose,
                match_id=self._mid)
            action = resp.get("action") if isinstance(resp.get("action"), dict) else None
            if action is not None:
                action = self._game.validate_action(self._state, seat, action)
            if action is None:
                action = {"type": request.action_type, "target": 0}
            return action, resp, False
        except Exception as e:  # 兜底：绝不卡死
            log.warning("seat %s 调用失败(%s)，走兜底", seat, e)
            fb = fallback_action(request)
            await self._emit("player.fallback",
                             {"seat": seat, "reason": str(e)[:200], "purpose": purpose},
                             vis=VisMeta(level="god"))
            return fb, {"speech": "", "monologue": "", "action": fb}, True

    def _memory_items(self, seat: int) -> list[str]:
        """该座位可见的事件历史投影（docs/agents-and-llm.md 记忆层）。

        遍历本局全量事件，按各事件的 VisMeta 过滤：public 全可见、seat 仅成员、
        god 不可见；发言类排除本人（自己说过的话无需再喂）。
        """
        lines: list[str] = []
        for ev in self._events:
            if not self._visible_to(ev.vis, seat):
                continue
            line = self._memory_line(ev, seat)
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

    def _memory_line(self, ev: Event, seat: int) -> str | None:
        """单个事件 → 记忆文本行（无信息量或本人发言返回 None）。"""
        t, p = ev.type, ev.payload
        if t in ("player.speech", "channel.message", "player.last_words"):
            speaker = p.get("seat")
            if speaker == seat:
                return None
            text = p.get("text", "")
            if t == "player.last_words":
                text = f"（遗言）{text}"
            return fence_memory([(speaker, text)])
        if t == "night.seer_result":
            verdict = "狼人" if p.get("verdict") == "wolf" else "好人"
            return f"你查验了 {p.get('target')} 号玩家：阵营是【{verdict}】。"
        if t == "night.resolved":
            deaths = p.get("deaths") or {}
            if deaths:
                desc = "、".join(f"{int(k)}号" for k in sorted(deaths))
                return f"第 {ev.day_index} 夜，{desc} 死亡。"
            return f"第 {ev.day_index} 夜，无人死亡。"
        if t == "vote.resolved":
            exile = p.get("exiled")
            if exile:
                return f"第 {ev.day_index} 天放逐投票：{exile} 号玩家出局。"
            return f"第 {ev.day_index} 天放逐投票：平票，无人出局。"
        return None

    # ---- Step 原语执行 ----

    async def _exec_step(self, step: Step) -> None:
        kind = step.kind
        p = step.params
        if kind == "noop":
            return
        if kind == "night_start":
            await self._exec_night_start()
        elif kind == "guard_turn":
            await self._exec_guard_turn()
        elif kind == "sheriff_elect":
            await self._exec_sheriff_elect(p)
        elif kind == "wolf_meeting":
            await self._exec_wolf_meeting(p)
        elif kind == "seer_check":
            await self._exec_seer_check(p)
        elif kind == "witch_turn":
            await self._exec_witch_turn(p)
        elif kind == "night_resolve":
            await self._exec_night_resolve(p)
        elif kind == "day_speech":
            await self._exec_serial_speech(
                {"speakers": sorted(s for s in self._state.roles if self._state.alive[s]),
                 "purpose": "speech"})
        elif kind == "day_vote":
            await self._exec_ballot({"voters": sorted(s for s in self._state.roles
                                                      if self._state.alive[s]),
                                     "purpose": "vote", "sheriff": self._state.extra.get("sheriff")})
        elif kind == "exile_resolve":
            await self._exec_exile_resolve(p)
        elif kind == "serial_speech":
            await self._exec_serial_speech(p)
        elif kind == "ballot":
            await self._exec_ballot(p)
        elif kind == "solo_action":
            await self._exec_solo_action(p)
        elif kind == "channel_meeting":
            await self._exec_channel_meeting(p)
        elif kind == "resolve":
            await self._exec_resolve(p)
        else:
            log.warning("未知 step kind: %s（跳过）", kind)

    # ---- 狼人杀步骤执行（经 game.action_schema 取 schema，逻辑保持游戏无关的形态） ----

    async def _exec_night_start(self) -> None:
        """新夜：清空动作收集；向存活枪手发技能状态通知（docs/games/werewolf.md）。"""
        self._state.extra["night"] = {}
        st = self._state
        for s in sorted(st.roles):
            if st.alive[s] and st.roles[s] in ("hunter", "wolf_king"):
                await self._emit("skill_state.notice", {"seat": s, "can_shoot": True},
                                 vis=VisMeta(level="seat", seats=[s]))

    async def _exec_guard_turn(self) -> None:
        """守卫守护：每晚一名（禁连守由 schema candidates 过滤）。"""
        st = self._state
        guard = self._role_seat(st, "guard")
        if guard is None:
            return
        request = self._game.action_schema(st, Step(kind="guard_turn"))
        action, resp, _fell = await self._ask(guard, request, "guard_turn")
        target = int(action.get("target") or 0)
        await self._emit("night.guard_target", {"seat": guard, "target": target},
                         vis=VisMeta(level="god"))
        if resp.get("monologue"):
            await self._emit("player.monologue", {"seat": guard, "text": resp["monologue"]})

    async def _exec_sheriff_elect(self, p: dict[str, Any]) -> None:
        """警长选举（standard 第 1 天，死讯公布前）：报名 → 宣言 → 投票 → PK → 授徽。"""
        st = self._state
        alive = sorted(s for s in st.roles if st.alive[s])
        req_reg = self._game.action_schema(st, Step(kind="sheriff_register"))
        regs: dict[int, bool] = {}

        async def reg(s: int) -> None:
            action, _resp, _fell = await self._ask(s, req_reg, "sheriff_register")
            regs[s] = bool(action.get("yes", True))

        await asyncio.gather(*(reg(s) for s in alive))
        registered = [s for s in alive if regs.get(s)]
        await self._emit("sheriff.registered", {"seats": registered})  # apply → elect_done
        if not registered or len(registered) >= len(alive):
            await self._emit("sheriff.badge", {"action": "destroy"})
            return
        if len(registered) == 1:
            await self._emit("sheriff.badge", {"action": "transfer", "to": registered[0]})
            return
        # 竞选宣言（串行）
        sp_req = self._game.action_schema(
            st, Step(kind="serial_speech", params={"purpose": "sheriff_speech"}))
        for s in registered:
            if st.alive.get(s) and sp_req is not None:
                await self._speech_round(s, sp_req, "sheriff_speech", channel=False)
        # 首轮投票：仅未上警者
        first = await self._exec_ballot(
            {"voters": [s for s in alive if s not in registered],
             "candidates": registered, "title": "警长投票", "purpose": "sheriff_vote"})
        winner, tie = first.get("exiled"), first.get("tie")
        if tie:
            tied = first.get("tied") or registered
            for s in tied:  # PK 发言
                if st.alive.get(s) and sp_req is not None:
                    await self._speech_round(s, sp_req, "sheriff_speech", channel=False)
            second = await self._exec_ballot(
                {"voters": alive, "candidates": tied, "title": "警长 PK 投票",
                 "purpose": "sheriff_vote"})
            if second.get("tie"):
                await self._emit("sheriff.badge", {"action": "destroy"})
                return
            winner = second.get("exiled")
        if winner:
            await self._emit("sheriff.badge", {"action": "transfer", "to": winner})
        else:
            await self._emit("sheriff.badge", {"action": "destroy"})

    async def _resolve_chain(self, causes: dict[int, str]) -> None:
        """死亡结算链：开枪（knife/exile 非毒死）→ 警徽移交。被枪杀者不连锁。"""
        st = self._state
        for seat in sorted(causes):
            if seat not in st.roles:
                continue
            cause = causes[seat]
            role = st.roles[seat]
            if role in ("hunter", "wolf_king") and cause in ("knife", "exile"):
                req = self._game.action_schema(st, Step(kind="gun"))
                if req is not None:
                    action, resp, _fell = await self._ask(seat, req, "gun")
                    target = int(action.get("target") or 0)
                    await self._emit("gun.shoot",
                                     {"seat": seat, "target": target,
                                      "text": resp.get("speech", "")},
                                     vis=VisMeta(level="god"))
                    if resp.get("monologue"):
                        await self._emit("player.monologue",
                                         {"seat": seat, "text": resp["monologue"]})
                    if target and st.extra.get("sheriff") == target:
                        await self._badge_solo(target)
            if st.extra.get("sheriff") == seat:
                await self._badge_solo(seat)

    async def _badge_solo(self, actor_seat: int) -> None:
        """警徽移交/撕毁（临终一次）。"""
        st = self._state
        req = self._game.action_schema(st, Step(kind="badge"))
        if req is None:
            return
        action, resp, _fell = await self._ask(actor_seat, req, "badge")
        target = int(action.get("target") or 0)
        if target and st.alive.get(target):
            await self._emit("sheriff.badge", {"action": "transfer", "to": target})
        else:
            await self._emit("sheriff.badge", {"action": "destroy"})
        if resp.get("monologue"):
            await self._emit("player.monologue",
                             {"seat": actor_seat, "text": resp["monologue"]})

    async def _exec_wolf_meeting(self, p: dict[str, Any]) -> None:
        state = self._state
        wolves = sorted(s for s in state.roles
                        if state.alive[s] and state.roles[s] in ("wolf", "wolf_king"))
        if not wolves:
            await self._emit("night.kill_target", {"target": 0, "decided_by": "no_wolf"})
            return
        rounds = (self._spec.wolf_meeting_rounds if self._spec else 2)
        await self._emit("channel.round.started", {"channel": "wolf", "members": wolves},
                         vis=VisMeta(level="god"))
        meeting = self._game.action_schema(state, Step(kind="wolf_meeting"))
        closing = self._game.action_schema(state, Step(kind="closing"))
        proposals: dict[int, int] = {}
        for wolf in wolves:
            # 轮内串行发言（v1：每狼 1 轮发言 + 收刀，防死循环：每狼总调用 ≤ rounds+1）
            for _ in range(max(rounds - 1, 0)):
                await self._speech_round(wolf, meeting, "wolf_channel", channel=True)
        # 收刀并行
        import asyncio as _a

        async def propose(w: int) -> None:
            action, _resp, _fell = await self._ask(w, closing, "closing")
            proposals[w] = int(action.get("target") or 0)

        await _a.gather(*(propose(w) for w in wolves))
        await self._emit("channel.round.ended", {"channel": "wolf", "proposals": proposals},
                         vis=VisMeta(level="god"))
        from app.games.werewolf import rules as wr
        valid = sorted(s for s in state.roles if state.alive[s])
        target, decided_by = wr.decide_kill(proposals, self._rng, valid_targets=set(valid))
        await self._emit("night.kill_target",
                         {"target": target, "decided_by": decided_by, "proposals": proposals},
                         vis=VisMeta(level="god"))

    async def _exec_seer_check(self, p: dict[str, Any]) -> None:
        state = self._state
        seer = self._role_seat(state, "seer")
        if seer is None:
            return
        request = self._game.action_schema(state, Step(kind="seer_check"))
        action, resp, _fell = await self._ask(seer, request, "seer_check")
        target = int(action.get("target") or 0)
        await self._emit("night.seer_query", {"seat": seer, "target": target},
                         vis=VisMeta(level="god"))
        if target and state.alive.get(target):
            verdict = "wolf" if state.roles[target] in ("wolf", "wolf_king") else "good"
            await self._emit("night.seer_result",
                             {"seat": seer, "target": target, "verdict": verdict})
            if resp.get("monologue"):
                await self._emit("player.monologue", {"seat": seer, "text": resp["monologue"]})

    async def _exec_witch_turn(self, p: dict[str, Any]) -> None:
        state = self._state
        witch = self._role_seat(state, "witch")
        if witch is None:
            return
        request = self._game.action_schema(state, Step(kind="witch_turn"))
        action, resp, _fell = await self._ask(witch, request, "witch_turn")
        act = str(action.get("type", "pass"))
        target = int(action.get("target") or 0)
        if act not in ("save", "poison"):
            act, target = "pass", 0
        if act == "poison" and (target == 0 or state.extra["used_poison"]):
            act, target = "pass", 0  # save 的 target 本就为 0（救刀口），不算非法
        if act == "save" and state.extra["used_save"]:
            act, target = "pass", 0
        await self._emit("night.witch_action",
                         {"seat": witch, "act": act, "target": target},
                         vis=VisMeta(level="god"))
        if resp.get("monologue"):
            await self._emit("player.monologue", {"seat": witch, "text": resp["monologue"]})

    async def _exec_night_resolve(self, p: dict[str, Any]) -> None:
        night = self._state.extra["night"]
        from app.games.werewolf import rules as wr
        res = wr.resolve_night(night)
        await self._emit("night.resolved", {"day": self._state.day, **res})
        causes = {int(k): v for k, v in (res.get("deaths") or {}).items()}
        if causes:
            await self._resolve_chain(causes)

    def _role_seat(self, state: GameState, role: str) -> int | None:
        for s in sorted(state.roles):
            if state.alive.get(s) and state.roles[s] == role:
                return s
        return None

    async def _exec_exile_resolve(self, p: dict[str, Any]) -> None:
        """放逐结算：遗言 → 开枪/移交链。"""
        exile = getattr(self, "_last_exile", None)
        if exile and self._state.alive.get(exile) is False:
            request = self._game.action_schema(self._state, Step(kind="last_words"))
            if request is not None:
                action, resp, _fell = await self._ask(exile, request, "last_words")
                await self._emit("player.last_words", {"seat": exile, "text": resp.get("speech", "")})
                if resp.get("monologue"):
                    await self._emit("player.monologue", {"seat": exile, "text": resp["monologue"]})
            await self._resolve_chain({int(exile): "exile"})

    async def _speech_round(self, seat: int, request: ActionRequest, purpose: str,
                            channel: bool) -> None:
        action, resp, _fell = await self._ask(seat, request, purpose)
        etype = "channel.message" if channel else "player.speech"
        await self._emit(etype, {"seat": seat, "text": resp.get("speech", "")})
        if resp.get("monologue"):
            await self._emit("player.monologue",
                             {"seat": seat, "text": resp["monologue"]})

    async def _exec_serial_speech(self, p: dict[str, Any]) -> None:
        for speaker in p["speakers"]:
            if not self._state.alive.get(speaker):
                continue
            request = self._game.action_schema(self._state,
                                               Step(kind="serial_speech", params=p))
            if request is None:
                continue
            await self._speech_round(speaker, request, p.get("purpose", "speech"), channel=False)

    async def _exec_ballot(self, p: dict[str, Any]) -> dict[str, Any]:
        """并行收集投票（防跟票）。返回 tally（含 tied 平票席位）。"""
        voters = [v for v in p["voters"] if self._state.alive.get(v)]
        request = self._game.action_schema(self._state, Step(kind="ballot", params=p))
        if request is None:
            return {"exiled": None, "tie": True, "tied": []}
        votes: dict[int, int] = {}

        async def collect(v: int) -> None:
            action, _resp, _fell = await self._ask(v, request, p.get("purpose", "vote"))
            target = int(action.get("target") or 0)
            votes[v] = target
            await self._emit("vote.cast", {"seat": v, "target": target})

        await asyncio.gather(*(collect(v) for v in voters))  # 并行收集防跟票
        from app.games.werewolf import rules as wr
        sheriff = p.get("sheriff")
        tally = wr.tally_votes(votes, sheriff=sheriff)
        # 平票席位（最高票并列，警长 2 票权重）
        weights: dict[int, int] = {}
        for v, t in votes.items():
            if not t:
                continue
            w = 2 if (sheriff is not None and v == sheriff) else 1
            weights[t] = weights.get(t, 0) + w
        top = max(weights.values()) if weights else 0
        tied = sorted(t for t, c in weights.items() if c == top)
        title = p.get("title", "放逐投票")
        await self._emit("vote.resolved",
                         {"votes": votes, "title": title, "tied": tied, **tally})
        if title.startswith("放逐"):
            self._last_exile = tally.get("exiled")
        return {**tally, "tied": tied}

    async def _exec_solo_action(self, p: dict[str, Any]) -> None:
        actor = p["actor"]
        request = self._game.action_schema(self._state, Step(kind="solo_action", params=p))
        if request is None:
            return
        action, resp, _fell = await self._ask(actor, request, p.get("purpose", "action"))
        await self._emit(p.get("event_type", "player.action"),
                         {"seat": actor, **action},
                         vis=VisMeta(level="god"))
        await self._emit_result_for(p, actor, action)

    async def _emit_result_for(self, p: dict[str, Any], actor: int, action: dict[str, Any]) -> None:
        """solo 动作的结果事件（可见性由插件标注，如验人结果仅本人可见）。"""
        ev_type = p.get("result_event")
        if ev_type:
            await self._emit(ev_type, {"seat": actor, "action": action})

    async def _exec_channel_meeting(self, p: dict[str, Any]) -> None:
        members = [m for m in p["members"] if self._state.alive.get(m)]
        rounds = p.get("rounds", 2)
        await self._emit("channel.round.started", {"channel": p.get("channel", ""), "members": members},
                         vis=VisMeta(level="god"))
        request = self._game.action_schema(self._state, Step(kind="channel_meeting", params=p))
        if request is None:
            return
        proposals: dict[int, int] = {}
        calls_used: dict[int, int] = {m: 0 for m in members}
        for r in range(rounds):
            for m in members:
                if calls_used[m] > rounds:  # 每狼总调用 ≤ rounds+1
                    continue
                calls_used[m] += 1
                await self._speech_round(m, request, p.get("purpose", "channel"), channel=True)
        # 收刀：并行提案
        closing = self._game.action_schema(self._state, Step(kind="closing", params=p))
        if closing is not None:

            async def propose(m: int) -> None:
                if calls_used[m] > rounds + 1:
                    proposals[m] = 0
                    return
                calls_used[m] += 1
                action, _resp, _fell = await self._ask(m, closing, "closing")
                proposals[m] = int(action.get("target") or 0)

            await asyncio.gather(*(propose(m) for m in members))
        await self._emit("channel.round.ended", {"channel": p.get("channel", ""), "proposals": proposals},
                         vis=VisMeta(level="god"))

    async def _exec_resolve(self, p: dict[str, Any]) -> None:
        """结算步骤：payload 由游戏插件准备好，直接落事件。"""
        for ev_spec in p.get("events", []):
            await self._emit(ev_spec["type"], ev_spec.get("payload", {}),
                             vis=VisMeta(**ev_spec.get("vis", {"level": "public"})))

    # ---- 主循环 ----

    async def run(self) -> GameResult | None:
        await self._repo.update_match(self._mid, status="running")
        await self._emit("match.started", {"seed": self._rng.random()})

        roles = self._game.deal(self._spec, self._rng) if self._spec else [
            type("R", (), {"seat": s, "role": "villager"})() for s in sorted(self._seat_meta)]
        role_map = {r.seat: r.role for r in roles}
        await self._repo.set_seat_roles(self._mid, role_map)
        for r in roles:
            await self._emit("role.dealt", {"seat": r.seat, "role": r.role},
                             vis=VisMeta(level="seat", seats=[r.seat]))
        self._state = self._game.initial_state(self._spec, roles) if self._spec else \
            self._game.initial_state(
                type("S", (), {"player_count": len(role_map), "role_list": []})(), roles)
        for seat, role in role_map.items():
            self._seat_meta.setdefault(seat, {})["role"] = role

        result: GameResult | None = None
        guard = 0
        while True:
            guard += 1
            if guard > 500:
                result = GameResult(winner="wolf", reason="步数超限保护")
                break
            if self._stop.is_set():
                result = GameResult(winner="wolf", reason="对局被手动终止")
                await self._emit("match.stopped", {})
                break
            result = self._game.check_winner(self._state)
            if result is not None:
                break
            step = self._game.next_step(self._state)
            # 每步统一发 phase.started（状态机推进依据 + 前端阶段边界事件）
            if step.kind != "noop":
                await self._emit("phase.started", {"phase": step.kind, "day": self._state.day})
            self._day = self._state.day
            self._phase = step.kind
            try:
                await asyncio.wait_for(self._exec_step(step), timeout=STEP_TIME_LIMIT_S)
            except asyncio.TimeoutError:
                log.error("步骤超时(%s)，跳过", step.kind)
                await self._emit("player.fallback", {"reason": "step_timeout", "step": step.kind},
                                 vis=VisMeta(level="god"))

        if result is not None:
            self._state.winner = result
            await self._emit("match.finished",
                             {"winner": result.winner, "reason": result.reason})
            await self._repo.update_match(
                self._mid, status="finished",
                result={"winner": result.winner, "reason": result.reason})
        elif self._stop.is_set():
            await self._repo.update_match(self._mid, status="stopped")
        return result
