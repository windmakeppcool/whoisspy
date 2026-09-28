"""一局完整流程（docs/backend/02-flow.md）。

直排 async 代码：夜间（狼聊/查验/用药/警长竞选/天亮）→ 白天（定序/发言/投票/放逐）。
MatchRun 是唯一的显式上下文：emit/ask/speak/ballot 原语 + 单写者事件流。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from random import Random
from typing import Any, Awaitable, Callable

from app.agent import AgentReply, ask as agent_ask, truncate_speech
from app.events import AskSpec, Event, GameResult, Vis, god, public, seat
from app.llm import LLMGateway, TraceRecorder
from app.prompts import (
    badge_spec,
    ballot_spec,
    closing_spec,
    gun_spec,
    register_spec,
    seer_check_spec,
    speech_order_spec,
    speech_spec,
    witch_turn_spec,
    wolf_meeting_spec,
)
from app.rules import (
    DEATH_POISON,
    GUN_ROLES,
    MAX_DAYS,
    ROLES,
    WOLF_MEETING_ROUNDS,
    WOLF_ROLES,
    check_winner,
    deal,
    decide_kill,
    resolve_night,
    tally_votes,
)
from app.state import GameState
from app.store import Store

log = logging.getLogger(__name__)

PHASE_LABELS = {
    "night_start": "入夜", "wolf_meeting": "狼队密谋", "seer_check": "预言家查验",
    "witch_turn": "女巫用药", "sheriff_elect": "警长竞选", "night_resolve": "天亮结算",
    "speech_order": "发言定序", "day_speech": "白天发言", "day_vote": "放逐投票",
    "exile_resolve": "放逐结算",
}


class _Stopped(Exception):
    """流程终止信号（调用数超限/手动终止），携带 reason。"""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class MatchRun:
    """一局的显式上下文（01-structure 四）。"""

    match_id: int
    seed: int
    state: GameState  # 唯一权威状态（只由 emit→apply 修改）
    seats: dict[int, dict[str, Any]]  # 座位快照（含 role/style/model/单价）
    gateway: LLMGateway
    store: Store
    max_calls: int = 600  # 单局调用数护栏（触发即 stopped）
    max_days: int = MAX_DAYS
    wolf_meeting_rounds: int = WOLF_MEETING_ROUNDS
    model_assignments: list[dict[str, Any]] = field(default_factory=list)
    trace: TraceRecorder | None = None
    rng: Random = field(init=False)
    events: list[Event] = field(default_factory=list, init=False, repr=False)
    _calls: int = field(default=0, init=False, repr=False)
    _emit_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
    on_event: Callable[[Event], None] | None = field(default=None, init=False, repr=False)
    # 事件直播钩子（CLI 终端逐行打印；与对局语义无关）

    def __post_init__(self) -> None:
        self.rng = Random(self.seed)

    # ---------- 原语 ----------

    async def emit(self, etype: str, payload: dict[str, Any] | None = None,
                   vis=None) -> Event:
        """落事件（seq 单写者分配）→ 立即归约 → 追加内存事件表 → trace。

        seq 分配与落库必须原子（并行收票时多个 ask 交错调用 emit）：
        锁内完成「分配 seq → INSERT → 归约」，保证 seq 严格递增且无重复。
        """
        async with self._emit_lock:
            ev = Event(seq=len(self.events) + 1, type=etype,
                       day_index=self.state.day, phase=self.state.phase,
                       payload=payload or {}, vis=vis or public())
            await self.store.append_event(self.match_id, ev)
            self.events.append(ev)
            self.state.apply(ev)
            if self.trace is not None:
                self.trace.write({"t": "event", "event": {
                    "seq": ev.seq, "type": ev.type, "payload": ev.payload}})
            if self.on_event is not None:
                self.on_event(ev)
        return ev

    def _seat_cfg(self, seat_no: int) -> dict[str, Any]:
        return self.seats.get(seat_no, {})

    async def ask(self, seat_no: int, spec: AskSpec, purpose: str,
                  phase: str | None = None) -> tuple[dict[str, Any], AgentReply, bool]:
        """向一个座位发起一次调用（含校验/兜底）；护栏计数（锁内原子）。"""
        async with self._emit_lock:
            self._calls += 1
            if self._calls > self.max_calls:
                raise _Stopped(f"LLM 调用数超限（>{self.max_calls}）")
        return await agent_ask(self.gateway, self.state, self._seat_cfg(seat_no),
                               self.events, seat_no, spec, purpose,
                               phase or self.state.phase, self.emit, self.match_id)

    async def monologue(self, seat_no: int, resp: AgentReply) -> None:
        """把这次调用的内心独白落成 god 级事件（D6：每次调用都有独白）。"""
        if resp.monologue:
            await self.emit("player.monologue",
                            {"seat": seat_no, "text": resp.monologue}, god())

    async def speak(self, seat_no: int, spec: AskSpec, purpose: str, *,
                    channel: bool = False, phase: str | None = None,
                    vis=None) -> None:
        """一次发言调用：落发言事件（240 字截断）+ 独白。

        channel=True 落 channel.message，可见性由调用方给（如狼队成员集）。
        """
        _a, resp, _f = await self.ask(seat_no, spec, purpose, phase)
        await self.emit("channel.message" if channel else "player.speech",
                        {"seat": seat_no, "text": truncate_speech(resp.speech)},
                        vis or public())
        await self.monologue(seat_no, resp)

    async def ballot(self, voters: list[int], candidates: list[int], *,
                     title: str, purpose: str,
                     phase: str = "ballot") -> dict[int, int]:
        """并行收票（防跟票），**按座位升序落 vote.cast**（P3 确定性）；返回 voter→target。"""
        spec = ballot_spec(title, candidates)
        got = await asyncio.gather(
            *(self.ask(v, spec, purpose, phase) for v in voters))
        by_voter = {v: got[i] for i, v in enumerate(voters)}
        votes: dict[int, int] = {}
        for voter in sorted(voters):
            action, resp, _f = by_voter[voter]
            target = int(action.get("target") or 0)
            votes[voter] = target
            await self.emit("vote.cast", {"seat": voter, "target": target})
            await self.monologue(voter, resp)
        return votes

    async def phase(self, kind: str) -> None:
        """阶段边界事件（中文 label 落 payload，投影层不再自维护映射，D31）。"""
        await self.emit("phase.started",
                        {"phase": kind, "day": self.state.day,
                         "label": PHASE_LABELS.get(kind, kind)})


# ---------- 小工具 ----------

def _alive(state: GameState) -> list[int]:
    return sorted(s for s in state.roles if state.alive.get(s))


def _role_seat(state: GameState, role: str) -> int | None:
    for s in sorted(state.roles):
        if state.alive.get(s) and state.roles[s] == role:
            return s
    return None


def _rotate(seats: list[int], start: int) -> list[int]:
    if start not in seats:
        return list(seats)
    i = seats.index(start)
    return seats[i:] + seats[:i]


# ---------- 夜间 ----------

async def night_phase(run: MatchRun) -> None:
    """入夜 → 狼聊 → 查验 → 用药 →（第 1 天警长竞选）→ 天亮结算。"""
    await run.emit("phase.started",
                   {"phase": "night_start", "day": run.state.day + 1,
                    "label": PHASE_LABELS["night_start"]})
    await run.emit("night.started", {"day": run.state.day})
    await _wolf_meeting(run)
    await _seer_check(run)
    await _witch_turn(run)
    if run.state.day == 1 and not run.state.elect_done:
        await sheriff_election(run)
    await _night_resolve(run)


async def _wolf_meeting(run: MatchRun) -> None:
    """狼队夜聊（串行，后一狼记忆层含前狼发言）→ 并行收刀 → 多数决定刀。"""
    await run.phase("wolf_meeting")
    state = run.state
    wolves = [s for s in _alive(state) if state.roles[s] in WOLF_ROLES]
    if not wolves:
        await run.emit("night.kill_target",
                       {"target": None, "decided_by": "no_wolf", "proposals": {}}, god())
        return
    await run.emit("channel.round.started", {"channel": "wolf", "members": wolves}, god())
    spec = wolf_meeting_spec(_alive(state))
    wolf_vis = Vis(level="seat", seats=wolves)  # 频道消息仅狼队成员可见
    for _ in range(max(run.wolf_meeting_rounds - 1, 0)):
        for wolf in wolves:  # 轮内串行
            await run.speak(wolf, spec, purpose="wolf_channel",
                            channel=True, phase="wolf_meeting", vis=wolf_vis)
    closing = closing_spec(_alive(state))
    got = await asyncio.gather(*(run.ask(w, closing, "closing", "closing")
                                 for w in wolves))
    proposals = {w: int(got[i][0].get("target") or 0) for i, w in enumerate(wolves)}
    await run.emit("channel.round.ended", {"channel": "wolf", "proposals": proposals}, god())
    target, decided_by = decide_kill(proposals, run.rng, valid_targets=set(_alive(state)))
    await run.emit("night.kill_target",
                   {"target": target, "decided_by": decided_by, "proposals": proposals}, god())


async def _seer_check(run: MatchRun) -> None:
    """预言家验人：查询过程 god 可见，结果仅本人可见。"""
    await run.phase("seer_check")
    seer = _role_seat(run.state, "seer")
    if seer is None:
        return
    spec = seer_check_spec(_alive(run.state))
    action, resp, _f = await run.ask(seer, spec, "seer_check")
    target = int(action.get("target") or 0)
    await run.emit("night.seer_query", {"seat": seer, "target": target}, god())
    if target and run.state.alive.get(target):
        verdict = "wolf" if run.state.roles[target] in WOLF_ROLES else "good"
        await run.emit("night.seer_result",
                       {"seat": seer, "target": target, "verdict": verdict}, seat(seer))
    await run.monologue(seer, resp)


async def _witch_turn(run: MatchRun) -> None:
    """女巫用药（合法性由校验保证：空刀夜不可用解药、药各一瓶）。"""
    await run.phase("witch_turn")
    witch = _role_seat(run.state, "witch")
    if witch is None:
        return
    has_save = not run.state.used_save
    knife = run.state.night.get("kill") if has_save else None
    if knife:
        knife_text = f"当晚刀口：{int(knife)} 号玩家（用解药可救活）。"
    elif has_save:
        knife_text = "今晚是空刀（无人被狼刀），解药无法使用。"
    else:
        knife_text = "解药已用完，你只知道毒药是否还在。"
    spec = witch_turn_spec(_alive(run.state), knife_text=knife_text,
                           action_type="save" if has_save else "poison")
    action, resp, _f = await run.ask(witch, spec, "witch_turn")
    act = str(action.get("type", "pass"))
    target = int(action.get("target") or 0)
    if act not in ("save", "poison"):
        act, target = "pass", 0
    await run.emit("night.witch_action", {"seat": witch, "act": act, "target": target}, god())
    await run.monologue(witch, resp)


# ---------- 警长竞选 ----------

async def sheriff_election(run: MatchRun) -> None:
    """第 1 天夜末、死讯公布前：报名 → 宣言 → 投票 → PK → 授徽（02-flow 3.5）。"""
    await run.phase("sheriff_elect")
    state = run.state
    alive = _alive(state)
    reg_spec = register_spec()
    got = await asyncio.gather(
        *(run.ask(s, reg_spec, "sheriff_register", "sheriff_register") for s in alive))
    registered = [s for s in alive if bool(got[alive.index(s)][0].get("yes", False))]
    await run.emit("sheriff.registered", {"seats": registered})

    if not registered or len(registered) >= len(alive):
        await run.emit("sheriff.badge", {"action": "destroy"})
        return
    if len(registered) == 1:
        await run.emit("sheriff.badge", {"action": "transfer", "to": registered[0]})
        return

    speech = speech_spec("sheriff_speech")
    for seat_no in registered:  # 竞选宣言（串行）
        await run.speak(seat_no, speech, "sheriff_speech", phase="serial_speech")

    voters = [s for s in alive if s not in registered]
    votes = await run.ballot(voters, registered, title="警长投票",
                             purpose="sheriff_vote", phase="ballot")
    tally = tally_votes(votes)
    await run.emit("vote.resolved", {"votes": votes, "title": "警长投票",
                                     "scope": "sheriff", **tally})
    if tally["tie"]:
        tied = tally["tied"] or list(registered)
        for seat_no in tied:  # PK 发言
            await run.speak(seat_no, speech, "sheriff_speech", phase="serial_speech")
        pk_voters = [s for s in _alive(state) if s not in tied]
        pk_votes = await run.ballot(pk_voters, tied, title="警长 PK 投票",
                                    purpose="sheriff_vote", phase="ballot")
        pk_tally = tally_votes(pk_votes)
        await run.emit("vote.resolved", {"votes": pk_votes, "title": "警长 PK 投票",
                                         "scope": "sheriff", **pk_tally})
        if pk_tally["tie"]:
            await run.emit("sheriff.badge", {"action": "destroy"})
            return
        winner = pk_tally["exiled"]
    else:
        winner = tally["exiled"]
    if winner:
        await run.emit("sheriff.badge", {"action": "transfer", "to": winner})
    else:
        await run.emit("sheriff.badge", {"action": "destroy"})


# ---------- 天亮结算与死亡链 ----------

async def _night_resolve(run: MatchRun) -> None:
    """结算矩阵出死讯（不含死因）→ 技能状态通知 → 开枪/警徽链。"""
    await run.phase("night_resolve")
    res = resolve_night(run.state.night)
    causes = {int(k): v for k, v in (res or {}).items()}
    await run.emit("night.resolved",
                   {"day": run.state.day, "deaths": {s: "" for s in causes}})
    if causes:
        await run.emit("night.death_cause", {"causes": causes}, god())
    for seat_no in sorted(run.state.roles):
        if run.state.roles[seat_no] not in GUN_ROLES:
            continue
        can_shoot = causes.get(seat_no) != DEATH_POISON
        await run.emit("skill_state.notice", {"seat": seat_no, "can_shoot": can_shoot},
                       seat(seat_no))
    if causes:
        await resolve_deaths(run, causes)


async def resolve_deaths(run: MatchRun, causes: dict[int, str]) -> None:
    """死亡结算链：开枪（非毒死猎人）→ 警徽处理。被枪杀者不连锁（02-flow 五）。"""
    state = run.state
    for seat_no in sorted(causes):
        if seat_no not in state.roles or state.alive.get(seat_no):
            continue  # 防御：真实存在且本轮已判死
        cause = causes[seat_no]
        if state.roles[seat_no] in GUN_ROLES and cause in ("knife", "exile"):
            spec = gun_spec(_alive(state))
            action, resp, _f = await run.ask(seat_no, spec, "gun", "gun")
            target = int(action.get("target") or 0)
            await run.emit("gun.shoot",
                           {"seat": seat_no, "target": target, "text": resp.speech})
            await run.monologue(seat_no, resp)
            if target and state.sheriff == target:
                await _badge_transfer(run, target)  # 被枪杀的警长也必须处理徽章
        if state.sheriff == seat_no:
            await _badge_transfer(run, seat_no)


async def _badge_transfer(run: MatchRun, actor: int) -> None:
    """警徽移交/撕毁（向 actor 问询继承者；0 = 撕毁）。"""
    state = run.state
    spec = badge_spec(_alive(state))
    action, resp, _f = await run.ask(actor, spec, "badge", "badge")
    target = int(action.get("target") or 0)
    if target and state.alive.get(target):
        await run.emit("sheriff.badge", {"action": "transfer", "to": target})
    else:
        await run.emit("sheriff.badge", {"action": "destroy"})
    await run.monologue(actor, resp)


# ---------- 白天 ----------

async def day_phase(run: MatchRun) -> None:
    """定序 → 发言 → 放逐投票 → 放逐结算（02-flow 四）。"""
    await _speech_order(run)
    await _day_speech(run)
    await _day_vote(run)
    await _exile_resolve(run)


async def _speech_order(run: MatchRun) -> None:
    """发言定序：警长指定首位，否则 rng；按座位升序环绕。"""
    await run.phase("speech_order")
    state = run.state
    alive = _alive(state)
    start: int | None = None
    decided_by = "rng"
    sheriff = state.sheriff
    if sheriff and state.alive.get(sheriff):
        spec = speech_order_spec(alive)
        action, resp, _f = await run.ask(sheriff, spec, "speech_order", "speech_order")
        target = int(action.get("target") or 0)
        if target in alive:
            start, decided_by = target, "sheriff"
        await run.monologue(sheriff, resp)
    if start is None:
        start = run.rng.choice(alive) if alive else 0
    await run.emit("day.speech_order",
                   {"order": _rotate(alive, start), "start": start,
                    "decided_by": decided_by})


async def _day_speech(run: MatchRun) -> None:
    """按定序结果依次发言（严格串行，观赛节奏感来源）。"""
    await run.phase("day_speech")
    state = run.state
    order = state.speech_order or _alive(state)
    spec = speech_spec("speech")
    for seat_no in order:
        if not state.alive.get(seat_no):
            continue  # 防御：中途死亡（正常流程不会发生）
        await run.speak(seat_no, spec, "speech", phase="day_speech")


async def _day_vote(run: MatchRun) -> None:
    """放逐投票：并行收票 → 计票（警长 2 票权重）→ vote.resolved（scope=exile）。"""
    await run.phase("day_vote")
    state = run.state
    alive = _alive(state)
    votes = await run.ballot(alive, alive, title="放逐投票",
                             purpose="vote", phase="day_vote")
    tally = tally_votes(votes, sheriff=state.sheriff)
    await run.emit("vote.resolved", {"votes": votes, "title": "放逐投票",
                                     "scope": "exile", "sheriff": state.sheriff,
                                     **tally})


async def _exile_resolve(run: MatchRun) -> None:
    """放逐结算：平票 → PK（平票者再发言 + 其余全体重投）→ 遗言 → 开枪/警徽链。"""
    await run.phase("exile_resolve")
    state = run.state
    exile = state.last_exile
    if exile is None and state.last_exile_tied:
        tied = [s for s in state.last_exile_tied if state.alive.get(s)]
        if tied:
            pk_spec = speech_spec("pk_speech")
            for seat_no in tied:  # PK 发言（串行）
                await run.speak(seat_no, pk_spec, "pk_speech", phase="serial_speech")
            pk_voters = [s for s in _alive(state) if s not in tied]
            pk_votes = await run.ballot(pk_voters, tied, title="放逐 PK 投票",
                                        purpose="vote", phase="ballot")
            pk_tally = tally_votes(pk_votes, sheriff=state.sheriff)
            await run.emit("vote.resolved", {"votes": pk_votes, "title": "放逐 PK 投票",
                                             "scope": "exile", **pk_tally})
            exile = pk_tally["exiled"]  # 再平票 → None → 平安日
    if not exile or not state.last_exile_was_alive:
        return  # 平安日 / 已死守门（D28.6）
    spec = speech_spec("last_words")
    _a, resp, _f = await run.ask(exile, spec, "last_words", "last_words")
    await run.emit("player.last_words", {"seat": exile,
                                         "text": truncate_speech(resp.speech)})
    await run.monologue(exile, resp)
    await resolve_deaths(run, {exile: "exile"})


# ---------- 开局与主循环 ----------

async def _deal(run: MatchRun) -> None:
    """发牌：写座位角色 + 逐座位 role.dealt（仅本人可见）+ 建初始状态。"""
    roles = deal(run.seed)
    await run.store.set_seat_roles(run.match_id, roles)
    for seat_no, role in roles.items():
        await run.emit("role.dealt", {"seat": seat_no, "role": role}, seat(seat_no))
        run.seats.setdefault(seat_no, {})["role"] = role
    run.state.roles = roles
    run.state.alive = {s: True for s in roles}


async def run_match(run: MatchRun) -> GameResult | None:
    """驱动一局（02-flow 二）：created → started → 发牌 → 夜/昼循环 → finished/stopped。

    返回 GameResult = 分出胜负；None = 被终止（超限/流程异常），reason 写入 match.stopped。
    """
    await run.emit("match.created", {
        "seed": run.seed, "roles": dict(ROLES),
        "wolf_meeting_rounds": run.wolf_meeting_rounds, "max_days": run.max_days,
        "model_assignments": run.model_assignments})
    await run.emit("match.started", {"seed": run.seed})
    await _deal(run)

    result: GameResult | None = None
    stop_reason: str | None = None
    try:
        while True:
            await night_phase(run)
            result = check_winner(run.state, day_cycle_done=False,
                                  max_days=run.max_days)
            if result is not None:
                break
            await day_phase(run)
            result = check_winner(run.state, day_cycle_done=True,
                                  max_days=run.max_days)
            if result is not None:
                break
    except _Stopped as e:
        stop_reason = e.reason
    except Exception as e:  # 流程异常：记 rule.error，绝不静默吞掉
        log.exception("对局流程异常")
        await run.emit("rule.error",
                       {"phase": run.state.phase, "reason": str(e)[:200]}, god())
        stop_reason = f"流程异常：{type(e).__name__}: {str(e)[:100]}"

    if result is not None:
        run.state.winner = result
        await run.emit("match.finished", {"winner": result.winner,
                                          "reason": result.reason})
        await run.store.finalize_match(run.match_id, "finished",
                                       {"winner": result.winner,
                                        "reason": result.reason})
        return result
    reason = stop_reason or "对局终止"
    await run.emit("match.stopped", {"reason": reason})
    await run.store.finalize_match(run.match_id, "stopped",
                                   {"winner": None, "reason": reason})
    return None