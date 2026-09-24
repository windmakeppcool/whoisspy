"""狼人杀 standard-9 的步内流程（游戏规则的唯一归属地）。

engine 只提供 StepContext 原语（发事件/问 agent/发言/收票/并发）；
本模块决定每一步问谁、怎么结算、写哪些事件——engine 不再 import 本模块。

每个 handler 对应状态机 next_step 产出的一个 step kind。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from app.core import VisMeta
from app.games.base import Step, StepContext
from app.games.werewolf import rules as wr

if TYPE_CHECKING:  # 仅类型标注：避免与 definition 形成运行时循环导入
    from app.games.werewolf.definition import WerewolfGame

log = logging.getLogger(__name__)

Handler = Callable[[Any, StepContext, Step], Awaitable[None]]
_HANDLERS: dict[str, Handler] = {}


def handler(kind: str) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        _HANDLERS[kind] = fn
        return fn
    return deco


async def play(game: "WerewolfGame", ctx: StepContext, step: Step) -> None:
    """按 step.kind 分派到具体流程；未知 kind 只告警不崩。"""
    fn = _HANDLERS.get(step.kind)
    if fn is None:
        log.warning("未知 step kind: %s（跳过）", step.kind)
        return
    await fn(game, ctx, step)


# ---------- 小工具 ----------

def _alive(state) -> list[int]:
    return sorted(s for s in state.roles if state.alive.get(s))


def _role_seat(state, role: str) -> int | None:
    for s in sorted(state.roles):
        if state.alive.get(s) and state.roles[s] == role:
            return s
    return None


def _rotate(seats: list[int], start: int) -> list[int]:
    if start not in seats:
        return list(seats)
    i = seats.index(start)
    return seats[i:] + seats[:i]


def _to_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


# ---------- 夜间 ----------

@handler("night_start")
async def _night_start(game: WerewolfGame, ctx: StepContext, step: Step) -> None:
    """入夜：清空本夜动作收集（经事件归约，保持「状态只能由 apply 改」）。"""
    await ctx.emit("night.started", {"day": ctx.state.day})


@handler("wolf_meeting")
async def _wolf_meeting(game: WerewolfGame, ctx: StepContext, step: Step) -> None:
    """狼队夜聊（频道串行）→ 并行收刀 → 多数决定刀（平票 rng，无合规目标=空刀）。"""
    state = ctx.state
    wolves = [s for s in _alive(state) if state.roles[s] in wr.WOLF_ROLES]
    if not wolves:
        await ctx.emit("night.kill_target",
                       {"target": None, "decided_by": "no_wolf", "proposals": {}},
                       VisMeta(level="god"))
        return
    rounds = max(int(ctx.spec.wolf_meeting_rounds), 1)
    await ctx.emit("channel.round.started", {"channel": "wolf", "members": wolves},
                   VisMeta(level="god"))
    meeting = game.action_schema(state, Step(kind="wolf_meeting"))
    if meeting is not None:
        for wolf in wolves:  # 轮内串行：后一狼的 prompt 含前狼发言
            for _ in range(max(rounds - 1, 0)):
                await ctx.speech(wolf, meeting, channel=True, purpose="wolf_channel")

    closing = game.action_schema(state, Step(kind="closing"))
    proposals: dict[int, int] = {}
    if closing is not None:
        got = await ctx.ask_many(wolves, closing, purpose="closing",
                                 step=Step(kind="closing"))
        proposals = {seat: _to_int(action.get("target"))
                     for seat, (action, _resp) in got.items()}
    await ctx.emit("channel.round.ended", {"channel": "wolf", "proposals": proposals},
                   VisMeta(level="god"))
    target, decided_by = wr.decide_kill(proposals, ctx.rng,
                                        valid_targets=set(_alive(state)))
    await ctx.emit("night.kill_target",
                   {"target": target, "decided_by": decided_by, "proposals": proposals},
                   VisMeta(level="god"))


@handler("seer_check")
async def _seer_check(game: WerewolfGame, ctx: StepContext, step: Step) -> None:
    """预言家验人：查询过程 god 可见，结果仅本人可见。"""
    state = ctx.state
    seer = _role_seat(state, wr.ROLE_SEER)
    if seer is None:
        return
    request = game.action_schema(state, Step(kind="seer_check"))
    if request is None:
        return
    action, resp = await ctx.ask(seer, request, purpose="seer_check")
    target = _to_int(action.get("target"))
    await ctx.emit("night.seer_query", {"seat": seer, "target": target},
                   VisMeta(level="god"))
    if target and state.alive.get(target):
        verdict = "wolf" if state.roles[target] in wr.WOLF_ROLES else "good"
        await ctx.emit("night.seer_result",
                       {"seat": seer, "target": target, "verdict": verdict})
    await ctx.monologue(seer, resp)


@handler("witch_turn")
async def _witch_turn(game: WerewolfGame, ctx: StepContext, step: Step) -> None:
    """女巫用药（合法性由 validate_action 保证：空刀夜不可用解药、药只有一瓶）。"""
    state = ctx.state
    witch = _role_seat(state, wr.ROLE_WITCH)
    if witch is None:
        return
    request = game.action_schema(state, Step(kind="witch_turn"))
    if request is None:
        return
    action, resp = await ctx.ask(witch, request, purpose="witch_turn")
    act = str(action.get("type", "pass"))
    target = _to_int(action.get("target"))
    if act not in ("save", "poison"):
        act, target = "pass", 0
    await ctx.emit("night.witch_action", {"seat": witch, "act": act, "target": target},
                   VisMeta(level="god"))
    await ctx.monologue(witch, resp)


@handler("night_resolve")
async def _night_resolve(game: WerewolfGame, ctx: StepContext, step: Step) -> None:
    """天亮结算：公布死讯（不含死因）→ 技能状态通知 → 开枪/警徽链。"""
    state = ctx.state
    res = wr.resolve_night(state.extra.get("night") or {})
    causes = {int(k): v for k, v in (res.get("deaths") or {}).items()}
    await ctx.emit("night.resolved",
                   {"day": state.day, "deaths": {seat: "" for seat in causes}})
    if causes:
        await ctx.emit("night.death_cause", {"causes": causes}, VisMeta(level="god"))
    # 夜序末尾：向枪手发技能状态通知（被毒死不能开枪）
    for seat in sorted(state.roles):
        if state.roles[seat] not in wr.GUN_ROLES:
            continue
        can_shoot = causes.get(seat) != wr.DEATH_BY_POISON
        await ctx.emit("skill_state.notice", {"seat": seat, "can_shoot": can_shoot},
                       VisMeta(level="seat", seats=[seat]))
    if causes:
        await _resolve_chain(game, ctx, causes)


# ---------- 警长竞选 ----------

@handler("sheriff_elect")
async def _sheriff_elect(game: WerewolfGame, ctx: StepContext, step: Step) -> None:
    """第 1 天夜末、死讯公布前：报名 → 宣言 → 投票 → PK → 授徽。"""
    state = ctx.state
    alive = _alive(state)
    reg_step = Step(kind="sheriff_register")
    reg_request = game.action_schema(state, reg_step)
    registered: list[int] = []
    if reg_request is not None:
        got = await ctx.ask_many(alive, reg_request, purpose="sheriff_register",
                                 step=reg_step)
        registered = [s for s in alive if bool(got[s][0].get("yes", False))]
    await ctx.emit("sheriff.registered", {"seats": registered})  # apply → elect_done

    if not registered or len(registered) >= len(alive):
        await ctx.emit("sheriff.badge", {"action": "destroy"})
        return
    if len(registered) == 1:
        await ctx.emit("sheriff.badge", {"action": "transfer", "to": registered[0]})
        return

    speech_step = Step(kind="serial_speech", params={"purpose": "sheriff_speech"})
    speech_request = game.action_schema(state, speech_step)

    async def campaign(seat: int) -> None:
        if state.alive.get(seat) and speech_request is not None:
            await ctx.speech(seat, speech_request, purpose="sheriff_speech",
                             step=speech_step)

    for seat in registered:  # 竞选宣言（串行）
        await campaign(seat)

    voters = [s for s in alive if s not in registered]
    votes = await ctx.collect_ballot(voters, registered, title="警长投票",
                                     step_kind="ballot", purpose="sheriff_vote")
    tally = wr.tally_votes(votes)
    await ctx.emit("vote.resolved", {"votes": votes, "title": "警长投票",
                                     "scope": "sheriff", **tally})
    winner = tally["exiled"]
    if tally["tie"]:
        tied = tally["tied"] or list(registered)
        for seat in tied:  # PK 发言
            await campaign(seat)
        # PK 重投：平票者之外的全体玩家（含已上警者）投票
        pk_voters = [s for s in _alive(state) if s not in tied]
        pk_votes = await ctx.collect_ballot(pk_voters, tied, title="警长 PK 投票",
                                            step_kind="ballot", purpose="sheriff_vote")
        pk_tally = wr.tally_votes(pk_votes)
        await ctx.emit("vote.resolved", {"votes": pk_votes, "title": "警长 PK 投票",
                                         "scope": "sheriff", **pk_tally})
        if pk_tally["tie"]:
            await ctx.emit("sheriff.badge", {"action": "destroy"})
            return
        winner = pk_tally["exiled"]
    if winner:
        await ctx.emit("sheriff.badge", {"action": "transfer", "to": winner})
    else:
        await ctx.emit("sheriff.badge", {"action": "destroy"})


# ---------- 白天 ----------

@handler("speech_order")
async def _speech_order(game: WerewolfGame, ctx: StepContext, step: Step) -> None:
    """发言定序：有警长由警长指定首位，否则 rng 随机起始；按座位升序环绕。"""
    state = ctx.state
    alive = _alive(state)
    order_step = Step(kind="speech_order")
    request = game.action_schema(state, order_step)
    start: int | None = None
    decided_by = "rng"
    sheriff = state.extra.get("sheriff")
    if request is not None and sheriff and state.alive.get(sheriff):
        action, resp = await ctx.ask(sheriff, request, purpose="speech_order",
                                     step=order_step)
        target = _to_int(action.get("target"))
        if target in alive:
            start, decided_by = target, "sheriff"
        await ctx.monologue(sheriff, resp)
    if start is None:
        start = ctx.rng.choice(alive) if alive else 0
    await ctx.emit("day.speech_order",
                   {"order": _rotate(alive, start), "start": start, "decided_by": decided_by})


@handler("day_speech")
async def _day_speech(game: WerewolfGame, ctx: StepContext, step: Step) -> None:
    """按定序结果依次发言（严格串行：观赛「追更」节奏感来源）。"""
    state = ctx.state
    speakers = list(step.params.get("speakers") or []) or _alive(state)
    speech_step = Step(kind="serial_speech", params=step.params)
    request = game.action_schema(state, speech_step)
    if request is None:
        return
    for seat in speakers:
        if not state.alive.get(seat):
            continue
        await ctx.speech(seat, request, purpose=step.params.get("purpose", "speech"),
                         step=speech_step)


@handler("day_vote")
async def _day_vote(game: WerewolfGame, ctx: StepContext, step: Step) -> None:
    """放逐投票：并行收票 → 计票（警长 2 票权重）→ 落 vote.resolved（scope=exile）。"""
    state = ctx.state
    alive = _alive(state)
    sheriff = state.extra.get("sheriff")
    votes = await ctx.collect_ballot(alive, alive, title="放逐投票",
                                     step_kind="day_vote", purpose="vote")
    tally = wr.tally_votes(votes, sheriff=sheriff)
    await ctx.emit("vote.resolved", {"votes": votes, "title": "放逐投票",
                                     "scope": "exile", "sheriff": sheriff, **tally})


@handler("exile_resolve")
async def _exile_resolve(game: WerewolfGame, ctx: StepContext, step: Step) -> None:
    """放逐结算：平票 → PK（平票者再发言 + 其余全体重投）→ 遗言 → 开枪/警徽链。"""
    state = ctx.state
    exile = state.extra.get("last_exile")
    if exile is None and state.extra.get("last_exile_tied"):
        tied = [s for s in state.extra["last_exile_tied"] if state.alive.get(s)]
        if tied:
            pk_step = Step(kind="serial_speech", params={"purpose": "pk_speech"})
            pk_request = game.action_schema(state, pk_step)
            if pk_request is not None:
                for seat in tied:
                    await ctx.speech(seat, pk_request, purpose="pk_speech", step=pk_step)
            pk_voters = [s for s in _alive(state) if s not in tied]
            pk_votes = await ctx.collect_ballot(pk_voters, tied, title="放逐 PK 投票",
                                                step_kind="ballot", purpose="vote")
            pk_tally = wr.tally_votes(pk_votes, sheriff=state.extra.get("sheriff"))
            await ctx.emit("vote.resolved", {"votes": pk_votes, "title": "放逐 PK 投票",
                                             "scope": "exile", **pk_tally})
            exile = pk_tally["exiled"]
    if not exile or not state.extra.get("last_exile_was_alive"):
        return  # 只对「本轮真的从存活变死亡」的座位走遗言/开枪链（D27）
    last_step = Step(kind="last_words")
    request = game.action_schema(state, last_step)
    if request is not None:
        _action, resp = await ctx.ask(exile, request, purpose="last_words", step=last_step)
        await ctx.emit("player.last_words", {"seat": exile, "text": resp.get("speech", "")})
        await ctx.monologue(exile, resp)
    await _resolve_chain(game, ctx, {int(exile): "exile"})


# ---------- 死亡结算链 ----------

async def _resolve_chain(game: WerewolfGame, ctx: StepContext,
                         causes: dict[int, str]) -> None:
    """开枪（非毒死的猎人）→ 警徽移交。被枪杀者不连锁（只对本轮真实死亡者触发）。"""
    state = ctx.state
    for seat in sorted(causes):
        if seat not in state.roles or state.alive.get(seat):
            continue
        cause = causes[seat]
        if state.roles[seat] in wr.GUN_ROLES and cause in ("knife", "exile"):
            gun_step = Step(kind="gun")
            request = game.action_schema(state, gun_step)
            if request is not None:
                action, resp = await ctx.ask(seat, request, purpose="gun", step=gun_step)
                target = _to_int(action.get("target"))
                await ctx.emit("gun.shoot",
                               {"seat": seat, "target": target,
                                "text": resp.get("speech", "")})
                await ctx.monologue(seat, resp)
                if target and state.extra.get("sheriff") == target:
                    await _badge_solo(game, ctx, target)
        if state.extra.get("sheriff") == seat:
            await _badge_solo(game, ctx, seat)


async def _badge_solo(game: WerewolfGame, ctx: StepContext, actor_seat: int) -> None:
    """警徽移交/撕毁（临终一次）。"""
    state = ctx.state
    badge_step = Step(kind="badge")
    request = game.action_schema(state, badge_step)
    if request is None:
        return
    action, resp = await ctx.ask(actor_seat, request, purpose="badge", step=badge_step)
    target = _to_int(action.get("target"))
    if target and state.alive.get(target):
        await ctx.emit("sheriff.badge", {"action": "transfer", "to": target})
    else:
        await ctx.emit("sheriff.badge", {"action": "destroy"})
    await ctx.monologue(actor_seat, resp)
