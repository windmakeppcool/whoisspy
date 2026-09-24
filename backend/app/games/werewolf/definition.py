"""狼人杀 GameDefinition（唯一板子 standard-9，docs/games/werewolf.md）。

State.extra 私有字段：
- night: {kill, saved, poison} 本夜动作收集
- used_save / used_poison: 女巫药（各一瓶）
- sheriff: 警长座位
- elect_done: 警长选举已完成（仅第 1 天一次）
- seer_results: 验人结果缓存
"""

from __future__ import annotations

from random import Random
from typing import Any

from app.core import (
    ActionRequest,
    BoardSpec,
    Event,
    GameResult,
    RoleAssignment,
    VisMeta,
)
from app.agents.protocol import fence_memory
from app.games.base import GameState, Step, StepContext
from app.games.werewolf import flow, rules as wr
from app.games.werewolf.prompts import SLICES

_PHASE_LABELS: dict[str, str] = {
    "night_start": "入夜", "wolf_meeting": "狼队密谋", "seer_check": "预言家查验",
    "witch_turn": "女巫用药", "sheriff_elect": "警长竞选", "night_resolve": "天亮结算",
    "speech_order": "发言定序", "day_speech": "白天发言", "day_vote": "放逐投票",
    "exile_resolve": "放逐结算",
}

# 各步骤允许的动作类型（validate_action 的唯一权威）
_STEP_ACTIONS: dict[str, tuple[str, ...]] = {
    "wolf_meeting": ("kill",),
    "closing": ("kill",),
    "seer_check": ("check",),
    "witch_turn": ("save", "poison", "pass"),
    "serial_speech": ("speech",),
    "day_speech": ("speech",),
    "last_words": ("speech",),
    "ballot": ("vote",),
    "day_vote": ("vote",),
    "sheriff_register": ("register",),
    "speech_order": ("speech_order",),
    "gun": ("shoot",),
    "badge": ("badge",),
}

# 各步骤的中性兜底动作（容错链用）：绝不替玩家做主。
# 注意女巫步的中性动作是 pass 而不是 save——request.action_type 是 save，
# 但「没答上来」绝不能用掉解药（docs/engine.md 容错红线）。
_NEUTRAL_ACTIONS: dict[str, dict[str, Any]] = {
    "wolf_meeting": {"type": "kill", "target": 0},
    "closing": {"type": "kill", "target": 0},
    "seer_check": {"type": "check", "target": 0},
    "witch_turn": {"type": "pass", "target": 0},
    "serial_speech": {"type": "speech", "target": 0},
    "day_speech": {"type": "speech", "target": 0},
    "last_words": {"type": "speech", "target": 0},
    "ballot": {"type": "vote", "target": 0},
    "day_vote": {"type": "vote", "target": 0},
    "sheriff_register": {"type": "register", "yes": False},
    "speech_order": {"type": "speech_order", "target": 0},
    "gun": {"type": "shoot", "target": 0},
    "badge": {"type": "badge", "target": 0},
}


class WerewolfGame:
    """standard-9 单板状态机（3 狼 + 预言家 + 女巫 + 猎人 + 3 民）。"""

    game_type = "werewolf"
    ruleset = wr.RULESET

    # ---------- 配置与发牌 ----------

    def validate_board(self, board_cfg: dict[str, Any]) -> BoardSpec:
        return wr.validate_board(board_cfg)

    def deal(self, spec: BoardSpec, rng: Random) -> list[RoleAssignment]:
        return wr.deal_roles(spec, rng)

    def initial_state(self, spec: BoardSpec, roles: list[RoleAssignment]) -> GameState:
        st = GameState(spec=spec, roles={r.seat: r.role for r in roles},
                       alive={r.seat: True for r in roles})
        st.extra = {
            "night": {}, "used_save": False, "used_poison": False,
            "sheriff": None, "seer_results": {}, "elect_done": False,
            "speech_order": [], "last_exile": None, "last_exile_tied": [],
            "last_exile_was_alive": False,
        }
        return st

    # ---------- 步内流程（实现在 flow.py：engine 只提供 StepContext 原语） ----------

    async def play(self, ctx: StepContext, step: Step) -> None:
        await flow.play(self, ctx, step)

    # ---------- 状态机 ----------

    def _after_night(self, state: GameState) -> Step:
        """夜末分流（D21）：第 1 天先警长竞选，竞选后公布死讯。"""
        if state.day == 1 and not state.extra.get("elect_done"):
            return Step(kind="sheriff_elect", params={})
        return Step(kind="night_resolve", params={})

    def next_step(self, state: GameState) -> Step:
        phase = state.phase

        if phase in ("", "init"):
            return Step(kind="night_start", params={})
        if phase == "night_start":
            return Step(kind="wolf_meeting", params={})
        if phase == "wolf_meeting":
            if self._has_alive(state, wr.ROLE_SEER):
                return Step(kind="seer_check", params={})
            if self._has_alive(state, wr.ROLE_WITCH):
                return Step(kind="witch_turn", params={})
            return self._after_night(state)
        if phase == "seer_check":
            if self._has_alive(state, wr.ROLE_WITCH):
                return Step(kind="witch_turn", params={})
            return self._after_night(state)
        if phase == "witch_turn":
            return self._after_night(state)
        if phase == "sheriff_elect":
            return Step(kind="night_resolve", params={})
        if phase == "night_resolve":
            return Step(kind="speech_order", params={})
        if phase == "speech_order":
            return Step(kind="day_speech",
                        params={"speakers": list(state.extra.get("speech_order") or []),
                                "purpose": "speech"})
        if phase == "day_speech":
            return Step(kind="day_vote", params={})
        if phase == "day_vote":
            return Step(kind="exile_resolve", params={})
        if phase == "exile_resolve":
            return Step(kind="night_start", params={})
        return Step(kind="night_start", params={})

    def _has_alive(self, state: GameState, role: str) -> bool:
        return any(state.alive[s] and state.roles[s] == role for s in state.roles)

    def _wolves(self, state: GameState) -> list[int]:
        return sorted(s for s in state.roles
                      if state.alive[s] and state.roles[s] in wr.WOLF_ROLES)

    def alive_seats(self, state: GameState) -> list[int]:
        return sorted(s for s in state.roles if state.alive[s])

    def _role_seat(self, state: GameState, role: str) -> int | None:
        for s in sorted(state.roles):
            if state.alive.get(s) and state.roles[s] == role:
                return s
        return None

    # ---------- 动作 schema ----------

    def action_schema(self, state: GameState, step: Step) -> ActionRequest | None:
        kind, p = step.kind, step.params
        alive_all = self.alive_seats(state)

        if kind in ("wolf_meeting", "closing"):
            prompt = ("狼队夜聊：与队友商量今晚刀谁，然后提交你的刀人目标。"
                      if kind == "wolf_meeting" else
                      "收刀：请提交最终刀人目标（0 为弃权/空刀）。")
            return ActionRequest(action_type="kill", candidates=alive_all, prompt=prompt)
        if kind == "seer_check":
            return ActionRequest(action_type="check", candidates=alive_all,
                                 prompt="预言家：选择今晚查验的玩家。0 为不查验。")
        if kind == "witch_turn":
            has_save = not state.extra["used_save"]
            has_poison = not state.extra["used_poison"]
            knife = state.extra["night"].get("kill") if has_save else None
            # 刀口信息只在使用解药时给（docs/games/werewolf.md「仅用药时知晓死者」）
            if knife:
                knife_text = f"当晚刀口：{int(knife)} 号玩家（用解药可救活）。"
            elif has_save:
                knife_text = "今晚是空刀（无人被狼刀），解药无法使用。"
            else:
                knife_text = "解药已用完，你只知道毒药是否还在。"
            return ActionRequest(
                action_type="save" if has_save else "poison",
                candidates=alive_all,
                prompt="女巫：提交 action，type 为 save(救刀口)/poison(毒人)/pass(不用药)。"
                       "target 为目标座位，pass/save 时 target=0。",
                extra={"knife_target": knife, "has_save": has_save,
                       "has_poison": has_poison},
                prompt_extra=knife_text)
        if kind == "serial_speech":
            purpose = p.get("purpose", "speech")
            prompt = ("发表警长竞选宣言：说服大家把票投给你。" if purpose == "sheriff_speech"
                      else "白天发言：陈述你的判断与推理。")
            return ActionRequest(action_type="speech", prompt=prompt)
        if kind == "speech_order":
            sheriff = state.extra.get("sheriff")
            if not (sheriff and state.alive.get(sheriff)):
                return None  # 无警长时由引擎 rng 随机起始，无需 agent 决策
            return ActionRequest(
                action_type="speech_order", candidates=alive_all,
                prompt="你是警长：指定今天从哪位玩家开始发言"
                       "（其余存活玩家按座位号顺序依次发言）。")
        if kind in ("ballot", "day_vote"):
            cands = p.get("candidates") or alive_all
            title = p.get("title", "放逐投票")
            return ActionRequest(action_type="vote", candidates=cands,
                                 prompt=f"投票（{title}）：投出你最怀疑的玩家（0 为弃权）。")
        if kind == "last_words":
            return ActionRequest(action_type="speech", prompt="你已出局，请发表遗言。")
        if kind == "sheriff_register":
            return ActionRequest(action_type="register", candidates=[],
                                 prompt="警长竞选：是否上警（action 的 yes 字段 true/false）。")
        if kind == "gun":
            return ActionRequest(action_type="shoot", candidates=alive_all,
                                 prompt="你倒下了——开枪带走一名玩家（0 为放弃开枪）。")
        if kind == "badge":
            return ActionRequest(action_type="badge", candidates=alive_all,
                                 prompt="临终移交警徽：target 为继承座位（0 = 撕毁警徽）。")
        return None

    # ---------- 动作校验（game-plugin.md：合法性唯一权威） ----------

    def neutral_action(self, state: GameState, step: Step) -> dict[str, Any]:
        """该步骤的中性兜底动作（容错链用，绝不替玩家做主）。"""
        return dict(_NEUTRAL_ACTIONS.get(step.kind, {"type": "pass", "target": 0}))

    def validate_action(self, state: GameState, step: Step, seat: int,
                        action: dict[str, Any]) -> dict[str, Any]:
        """校验并归一动作；任何非法输入降级为中性动作。

        规则：
        - 动作类型必须是该步骤允许的类型之一；
        - target 必须同时满足「存活」与「在该步骤的候选集内」（候选集来自 step.params，
          例如警长选举只能投上警者、PK 只能投平票者），0 表示弃权/放弃；
        - 女巫用药还受药数与刀口约束（空刀夜不能用解药）。
        """
        neutral = self.neutral_action(state, step)
        allowed = _STEP_ACTIONS.get(step.kind, ())
        atype = str(action.get("type", "") or "")
        if atype not in allowed:
            return neutral

        alive = set(self.alive_seats(state))
        if atype == "register":
            return {"type": "register", "yes": bool(action.get("yes", False))}
        if atype in ("speech",):
            return {"type": "speech", "target": 0}

        # 候选集来自插件构造的子步骤 params（引擎只透传）
        candidates = {_to_int(c) for c in (step.params.get("candidates") or [])}
        valid_targets = (candidates & alive) if candidates else alive

        target = _to_int(action.get("target"))
        if atype == "save":
            # 解药只救当晚刀口，且空刀夜不可用药（docs/games/werewolf.md）
            knife = state.extra["night"].get("kill")
            if state.extra["used_save"] or not knife:
                return neutral
            return {"type": "save", "target": 0}
        if atype == "poison":
            if state.extra["used_poison"] or target not in valid_targets:
                return neutral
            return {"type": "poison", "target": target}
        # 其余类型：target 不在合法候选内 → 按弃权处理（不是整条动作作废）
        if target not in valid_targets:
            target = 0
        return {"type": atype, "target": target}

    # ---------- 归约 ----------

    def apply(self, state: GameState, event: Event) -> None:
        p = event.payload
        t = event.type
        if t == "phase.started":
            state.phase = p.get("phase", state.phase)
            if p.get("phase") == "night_start":
                state.day += 1
        elif t == "night.started":
            state.extra["night"] = {}  # 入夜清空本夜动作收集（事件驱动，非外部改写）
        elif t == "night.kill_target":
            state.extra["night"]["kill"] = p.get("target")
        elif t == "night.seer_result":
            state.extra["seer_results"][p.get("target")] = p.get("verdict")
        elif t == "night.witch_action":
            act = p.get("act")
            if act == "save":
                state.extra["used_save"] = True
                state.extra["night"]["saved"] = True
            elif act == "poison":
                state.extra["used_poison"] = True
                state.extra["night"]["poison"] = p.get("target")
        elif t == "night.resolved":
            _mark_dead(state, (p.get("deaths") or {}).keys())
        elif t == "day.speech_order":
            state.extra["speech_order"] = [int(s) for s in (p.get("order") or [])]
        elif t == "vote.resolved" and p.get("scope") == "exile":
            exile = p.get("exiled")
            state.extra["last_exile"] = exile
            state.extra["last_exile_tied"] = list(p.get("tied") or [])
            # 只对「本轮真实发生 存活→死亡 迁移」的座位触发遗言/开枪链（D27）：
            # 先记录投票前的存活状态，再判死。
            state.extra["last_exile_was_alive"] = (
                bool(exile) and bool(state.alive.get(int(exile), False)))
            _mark_dead(state, [exile])
        elif t == "gun.shoot":
            _mark_dead(state, [p.get("target")])
        elif t == "sheriff.registered":
            state.extra["elect_done"] = True
        elif t == "sheriff.badge":
            if p.get("action") == "transfer":
                state.extra["sheriff"] = p.get("to")
            else:
                state.extra["sheriff"] = None

    # ---------- 胜负 ----------

    def check_winner(self, state: GameState) -> GameResult | None:
        return wr.check_winner(state.roles, state.alive, day=state.day,
                               max_days=state.spec.max_days,
                               day_cycle_done=state.phase == "exile_resolve")

    def phase_day(self, state: GameState, step: Step) -> int:
        """phase.started 事件归属的天数：夜首推进（与 apply 的天数推进保持一致）。"""
        return state.day + 1 if step.kind == "night_start" else state.day

    # ---------- 记忆投影（记忆层唯一权威，docs/agents-and-llm.md） ----------

    def memory_line(self, event: Event) -> str | None:
        """单条可见事件 → 记忆文本行；None 表示该事件不进记忆。

        记忆是「本座可见事件的历史投影」：凡是本座可见的事件都应在这里有落点，
        尤其是票型（vote.cast）、警徽归属、开枪结果——它们直接决定推理质量。
        少数事件刻意不落点（信息已由其它层给出，重复只会灌水）：
        - role.dealt：身份层已声明自己的角色；
        - night.started：紧随其前的 phase.started 已给「第 N 天·入夜」；
        - match.created：match.started 已覆盖。
        """
        t, p = event.type, event.payload
        if t in ("player.speech", "channel.message", "player.last_words"):
            text = str(p.get("text", ""))
            if t == "player.last_words":
                text = f"（遗言）{text}"
            return fence_memory([(int(p.get("seat") or 0), text)])
        if t == "phase.started":
            phase = str(p.get("phase", ""))
            return f"【第 {int(p.get('day', event.day_index))} 天·{_PHASE_LABELS.get(phase, phase)}】"
        if t == "day.speech_order":
            order = p.get("order") or []
            return ("本轮发言顺序：" + "→".join(f"{int(s)} 号" for s in order) + "。"
                    if order else None)
        if t == "match.started":
            return "对局开始。"
        if t == "match.finished":
            winner = "狼人阵营" if p.get("winner") == "wolf" else "好人阵营"
            return f"对局结束：{winner}获胜（{p.get('reason', '')}）。"
        if t == "night.resolved":
            deaths = p.get("deaths") or {}
            if not deaths:
                return f"第 {event.day_index} 夜：平安夜，无人死亡。"
            return f"第 {event.day_index} 夜：{_seats(deaths)} 死亡。"
        if t == "night.seer_result":
            verdict = "狼人" if p.get("verdict") == "wolf" else "好人"
            return f"你查验了 {p.get('target')} 号玩家：阵营是【{verdict}】。"
        if t == "vote.cast":
            seat, target = int(p.get("seat") or 0), int(p.get("target") or 0)
            return f"{seat} 号弃票。" if not target else f"{seat} 号投给了 {target} 号。"
        if t == "vote.resolved":
            if p.get("scope") == "sheriff":
                if p.get("tie"):
                    return f"警长投票平票（{_seats(p.get('tied'))}）。"
                return f"警长投票结果：{p.get('exiled')} 号当选警长。"
            if p.get("tie"):
                return f"第 {event.day_index} 天放逐投票平票，无人出局。"
            return f"第 {event.day_index} 天放逐投票：{p.get('exiled')} 号出局。"
        if t == "sheriff.registered":
            seats = p.get("seats") or []
            return "上警报名：" + ("、".join(f"{int(s)} 号" for s in seats) + "。"
                                 if seats else "无人上警。")
        if t == "sheriff.badge":
            if p.get("action") == "transfer":
                return f"警徽归属：{p.get('to')} 号。"
            return "警徽被撕毁，本局再无警长。"
        if t == "gun.shoot":
            if not p.get("target"):
                return f"{p.get('seat')} 号开枪但未带走任何人。"
            return f"{p.get('seat')} 号开枪带走了 {p.get('target')} 号。"
        if t == "skill_state.notice":
            return ("你的技能状态：可以开枪。" if p.get("can_shoot")
                    else "你的技能状态：今晚不能开枪。")
        return None

    # ---------- 可见性 ----------

    def visibility(self, event: Event, state: GameState) -> VisMeta:
        t = event.type
        if t in ("night.kill_target", "night.witch_action", "night.death_cause",
                 "channel.round.started", "channel.round.ended", "player.monologue",
                 "player.fallback", "plugin.error"):
            return VisMeta(level="god")
        if t == "channel.message":
            return VisMeta(level="seat", seats=self._wolves(state))
        if t == "night.seer_query":
            return VisMeta(level="god")
        if t == "night.seer_result":
            seer = self._role_seat(state, wr.ROLE_SEER)
            return VisMeta(level="seat", seats=[seer] if seer else [])
        if t == "skill_state.notice":
            seat = event.payload.get("seat")
            return VisMeta(level="seat", seats=[seat] if seat else [])
        if t == "role.dealt":
            return VisMeta(level="seat", seats=[event.payload.get("seat")])
        return VisMeta(level="public")

    # ---------- 规则切片 ----------

    def rule_slices(self) -> dict[str, str]:
        return dict(SLICES)

    def slices_for(self, step: Step) -> list[str]:
        base = ["overview"]
        mapping = {
            "wolf_meeting": ["night_wolf"], "closing": ["night_wolf"],
            "seer_check": ["night_seer"], "witch_turn": ["night_witch"],
            "day_speech": ["day_speech", "sheriff_power"],
            "last_words": ["day_speech"],
            "serial_speech": ["day_speech"], "sheriff_elect": ["sheriff_elect"],
            "sheriff_register": ["sheriff_elect"],
            "speech_order": ["day_speech", "sheriff_power"],
            "day_vote": ["day_vote", "sheriff_power"],
            "ballot": ["day_vote"], "exile_resolve": ["day_vote"],
            "badge": ["sheriff_power"], "gun": ["gun_skill"],
        }
        return base + mapping.get(step.kind, [])


def _mark_dead(state: GameState, seats) -> None:
    """只有真实存在的座位才能被标记死亡（防幻觉座位污染 alive 表）。"""
    for seat in seats:
        if seat is None:
            continue
        key = int(seat)
        if key in state.roles:
            state.alive[key] = False


def _seats(seats) -> str:
    """座位集合 → 「1 号、3 号」文本。"""
    return "、".join(f"{int(s)} 号" for s in sorted(seats or []))


def _to_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
