"""类型化对局状态与 reducer（docs/backend/04-state.md）。

GameState 只能由 apply(event) 修改；apply 之外的代码不得改动任何字段。
折叠一致性：从库读任意前缀事件逐条 apply ≡ 现场状态。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.events import Event, GameResult


@dataclass
class GameState:
    """对局状态（全字段具名，无私有字典；day=N 覆盖第 N 夜与第 N 天白天）。"""

    roles: dict[int, str]  # seat -> role
    alive: dict[int, bool]
    day: int = 0  # 入夜时 +1
    phase: str = ""  # 最近一次 phase.started 的 kind
    sheriff: int | None = None  # 警长座位（destroy 后回 None）
    elect_done: bool = False  # 警长选举流程已走过（无论徽章归属）
    used_save: bool = False  # 女巫解药
    used_poison: bool = False  # 女巫毒药
    night: dict[str, Any] = field(default_factory=dict)  # 本夜收集：kill/saved/poison
    seer_results: dict[int, str] = field(default_factory=dict)  # target -> verdict
    speech_order: list[int] = field(default_factory=list)  # 当天发言顺序
    last_exile: int | None = None
    last_exile_tied: list[int] = field(default_factory=list)
    last_exile_was_alive: bool = False  # 放逐守门标记（判死前取样，D28.6）
    winner: GameResult | None = None

    def snapshot(self) -> dict[str, Any]:
        """全字段可读快照（trace 每阶段末尾落一条，debug 用）。"""
        return {
            "day": self.day,
            "phase": self.phase,
            "sheriff": self.sheriff,
            "elect_done": self.elect_done,
            "used_save": self.used_save,
            "used_poison": self.used_poison,
            "night": dict(self.night),
            "seer_results": dict(self.seer_results),
            "speech_order": list(self.speech_order),
            "last_exile": self.last_exile,
            "last_exile_tied": list(self.last_exile_tied),
            "last_exile_was_alive": self.last_exile_was_alive,
            "alive": {s: a for s, a in self.alive.items()},
        }

    def apply(self, event: Event) -> None:
        """归约一条事件（唯一的状态修改入口）。"""
        p = event.payload
        t = event.type
        if t == "phase.started":
            self.phase = str(p.get("phase", self.phase))
            if self.phase == "night_start":
                self.day += 1
        elif t == "night.started":
            self.night = {}
        elif t == "night.kill_target":
            self.night["kill"] = p.get("target")  # None/0 = 空刀
        elif t == "night.seer_result":
            self.seer_results[_to_int(p.get("target"))] = str(p.get("verdict", ""))
        elif t == "night.witch_action":
            act = p.get("act")
            if act == "save":
                self.used_save = True
                self.night["saved"] = True
            elif act == "poison":
                self.used_poison = True
                self.night["poison"] = p.get("target")
        elif t == "night.resolved":
            _mark_dead(self, (p.get("deaths") or {}).keys())
        elif t == "vote.resolved" and p.get("scope") == "exile":
            exile = p.get("exiled")
            self.last_exile = exile
            self.last_exile_tied = list(p.get("tied") or [])
            # 判死前取样：只有「本轮真的从存活变死亡」才走遗言/开枪链
            self.last_exile_was_alive = (
                bool(exile) and bool(self.alive.get(_to_int(exile), False)))
            _mark_dead(self, [exile])
        elif t == "gun.shoot":
            _mark_dead(self, [p.get("target")])
        elif t == "sheriff.registered":
            self.elect_done = True
        elif t == "sheriff.badge":
            if p.get("action") == "transfer":
                self.sheriff = _to_int(p.get("to"))
            else:
                self.sheriff = None
        elif t == "day.speech_order":
            self.speech_order = [_to_int(s) for s in (p.get("order") or [])]
        # 其余事件不改状态（role.dealt/match.*/channel.*/player.*/vote.cast/god 级诊断）


def _mark_dead(state: GameState, seats) -> None:
    """判死防御：只接受 roles 中真实存在的座位（幻觉座位/None 静默忽略）。"""
    for seat in seats:
        if seat is None:
            continue
        key = _to_int(seat)
        if key in state.roles:
            state.alive[key] = False


def _to_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0