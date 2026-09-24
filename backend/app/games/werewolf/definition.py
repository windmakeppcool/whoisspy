"""狼人杀 GameDefinition：minimal 与 standard-12 两套状态机（docs/games/werewolf.md）。

State.extra 私有字段：
- night: {kill, guard, saved, poison} 本夜动作收集
- used_save / used_poison: 女巫药（standard）
- last_guard: 守卫上夜守护目标（standard，禁连守）
- sheriff: 警长座位（standard）
- elect_done: 警长选举已完成（standard，仅 day1 一次）
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
from app.games.base import GameState, Step
from app.games.werewolf import rules as wr
from app.games.werewolf.prompts import SLICES


class WerewolfGame:
    """两个 ruleset 共用一个类，行为按 spec.ruleset 分叉。"""

    game_type = "werewolf"

    def __init__(self, ruleset: str = "minimal"):
        self.ruleset = ruleset

    # ---------- 配置与发牌 ----------

    def validate_board(self, board_cfg: dict[str, Any]) -> BoardSpec:
        return wr.validate_board(board_cfg, self.ruleset)

    def deal(self, spec: BoardSpec, rng: Random) -> list[RoleAssignment]:
        return wr.deal_roles(spec, rng)

    def initial_state(self, spec: BoardSpec, roles: list[RoleAssignment]) -> GameState:
        st = GameState(spec=spec, roles={r.seat: r.role for r in roles},
                       alive={r.seat: True for r in roles})
        st.extra = {
            "night": {}, "used_save": False, "used_poison": False,
            "last_guard": None, "sheriff": None, "seer_results": {},
            "elect_done": False,
            # standard-9 与 standard-12 共享标准机制（警长/女巫/开枪）；
            # 守卫步由 _has_alive(guard) 自动跳过（9 人局无守卫）
            "standard": spec.ruleset.startswith("standard"),
        }
        return st

    # ---------- 状态机 ----------

    def _after_night(self, state: GameState) -> Step:
        """夜末分流（D21）：standard 第 1 天先警长竞选，竞选后公布死讯。"""
        if state.extra["standard"] and state.day == 1 \
                and not state.extra.get("elect_done"):
            return Step(kind="sheriff_elect", params={})
        return Step(kind="night_resolve", params={})

    def next_step(self, state: GameState) -> Step:
        std: bool = state.extra["standard"]
        phase = state.phase

        if phase in ("", "init"):
            return Step(kind="night_start", params={})

        if phase == "night_start":
            # standard 夜序：守卫守护 → 狼刀 → 预言家 → 女巫
            if std and self._has_alive(state, wr.ROLE_GUARD):
                return Step(kind="guard_turn", params={})
            return Step(kind="wolf_meeting", params={})
        if phase == "guard_turn":
            return Step(kind="wolf_meeting", params={})
        if phase == "wolf_meeting":
            if self._has_alive(state, wr.ROLE_SEER):
                return Step(kind="seer_check", params={})
            if std and self._has_alive(state, wr.ROLE_WITCH):
                return Step(kind="witch_turn", params={})
            return self._after_night(state)
        if phase == "seer_check":
            if std and self._has_alive(state, wr.ROLE_WITCH):
                return Step(kind="witch_turn", params={})
            return self._after_night(state)
        if phase == "witch_turn":
            return self._after_night(state)
        if phase == "sheriff_elect":
            return Step(kind="night_resolve", params={})
        if phase == "night_resolve":
            return Step(kind="day_speech", params={})
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

    def _role_seat(self, state: GameState, role: str) -> int | None:
        for s in sorted(state.roles):
            if state.alive.get(s) and state.roles[s] == role:
                return s
        return None

    # ---------- 动作 schema ----------

    def action_schema(self, state: GameState, step: Step) -> ActionRequest | None:
        kind, p = step.kind, step.params
        alive_all = sorted(s for s in state.roles if state.alive[s])

        if kind in ("wolf_meeting", "channel_meeting"):
            return ActionRequest(action_type="kill", candidates=alive_all,
                                 prompt="狼队夜聊：与队友商量今晚刀谁，然后提交你的刀人目标。")
        if kind == "closing":
            return ActionRequest(action_type="kill", candidates=alive_all,
                                 prompt="收刀：请提交最终刀人目标（0 为弃权/空刀）。")
        if kind == "seer_check":
            return ActionRequest(action_type="check", candidates=alive_all,
                                 prompt="预言家：选择今晚查验的玩家。0 为不查验。")
        if kind == "witch_turn":
            return ActionRequest(
                action_type="save" if not state.extra["used_save"] else "poison",
                candidates=alive_all,
                prompt="女巫：提交 action，type 为 save(救刀口)/poison(毒人)/pass(不用药)。"
                       "target 为目标座位，pass/save 时 target=0。",
                extra={"night_kill": state.extra["night"].get("kill") if not state.extra["used_save"] else None,
                       "has_save": not state.extra["used_save"],
                       "has_poison": not state.extra["used_poison"]})
        if kind == "guard_turn":
            forbidden = state.extra.get("last_guard")  # 禁连守
            cands = [s for s in alive_all if s != forbidden]
            return ActionRequest(action_type="guard", candidates=cands,
                                 prompt="守卫：选择今晚守护的玩家（不能连续两晚守同一人，可守自己）。0 为不守。")
        if kind in ("serial_speech", "day_speech"):
            purpose = p.get("purpose", "speech")
            if purpose == "sheriff_speech":
                return ActionRequest(action_type="speech",
                                     prompt="发表警长竞选宣言：说服大家把票投给你。")
            return ActionRequest(action_type="speech",
                                 prompt="白天发言：陈述你的判断与推理。")
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
        if kind == "solo_action":
            at = p.get("action_type", "vote")
            return ActionRequest(action_type=at,
                                 candidates=p.get("candidates") or alive_all,
                                 prompt=p.get("prompt", "执行你的行动。"))
        return None

    # ---------- 动作校验 ----------

    def validate_action(self, state: GameState, seat: int, action: dict[str, Any]) -> dict[str, Any]:
        t = str(action.get("type", ""))
        target = int(action.get("target") or 0)
        yes = action.get("yes")
        out: dict[str, Any] = {"type": t, "target": target}
        if isinstance(yes, bool):
            out["yes"] = yes
        return out

    # ---------- 归约 ----------

    def apply(self, state: GameState, event: Event) -> None:
        p = event.payload
        t = event.type
        if t == "phase.started":
            state.phase = p.get("phase", state.phase)
            if p.get("phase") == "night_start":
                state.day += 1
        elif t == "night.kill_target":
            state.extra["night"]["kill"] = p.get("target")
        elif t == "night.guard_target":
            state.extra["night"]["guard"] = p.get("target")
            state.extra["last_guard"] = p.get("target")
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
            for seat_s in (p.get("deaths") or {}):
                state.alive[int(seat_s)] = False
        elif t == "vote.resolved":
            exile = p.get("exiled")
            if exile:
                state.alive[int(exile)] = False
        elif t == "gun.shoot":
            tgt = p.get("target")
            if tgt:
                state.alive[int(tgt)] = False
        elif t == "sheriff.registered":
            state.extra["elect_done"] = True
        elif t == "sheriff.badge":
            if p.get("action") == "transfer":
                state.extra["sheriff"] = p.get("to")
            else:
                state.extra["sheriff"] = None

    # ---------- 胜负 ----------

    def check_winner(self, state: GameState) -> GameResult | None:
        return wr.check_winner(state.spec.ruleset, state.roles, state.alive,
                               day=state.day, max_days=state.spec.max_days)

    # ---------- 可见性 ----------

    def visibility(self, event: Event, state: GameState) -> VisMeta:
        t = event.type
        if t in ("night.kill_target", "night.guard_target", "night.witch_action",
                 "channel.round.started", "channel.round.ended"):
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
        if t in ("player.fallback", "player.monologue"):
            return VisMeta(level="god")
        return VisMeta(level="public")

    # ---------- 规则切片 ----------

    def rule_slices(self) -> dict[str, str]:
        return dict(SLICES)

    def slices_for(self, step: Step) -> list[str]:
        base = ["overview"]
        mapping = {
            "wolf_meeting": ["night_wolf"], "closing": ["night_wolf"],
            "channel_meeting": ["night_wolf"],
            "seer_check": ["night_seer"], "witch_turn": ["night_witch"],
            "guard_turn": ["night_guard"],
            "day_speech": ["day_speech"], "last_words": ["day_speech"],
            "serial_speech": ["day_speech"],
            "day_vote": ["day_vote"], "ballot": ["day_vote"],
            "exile_resolve": ["day_vote"],
            "sheriff_elect": ["sheriff_elect"], "sheriff_register": ["sheriff_elect"],
            "badge": ["sheriff_power"], "gun": ["gun_skill"],
        }
        return base + mapping.get(step.kind, [])
