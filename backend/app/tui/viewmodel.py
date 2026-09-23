"""事件 → ViewModel 投影（纯函数）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core import Event


PHASE_LABELS: dict[str, str] = {
    "night_start": "夜幕降临", "wolf_meeting": "狼队密谋", "seer_check": "预言家行动",
    "witch_turn": "女巫行动", "night_resolve": "夜间结算", "day_speech": "白天发言",
    "day_vote": "放逐投票", "exile_resolve": "放逐结算",
}


@dataclass
class MatchVM:
    """对局 ViewModel。"""
    phase: str = "idle"
    day: int = 0
    label: str = "等待开局"
    feed: list[dict[str, Any]] = field(default_factory=list)
    seats: list[dict[str, Any]] = field(default_factory=list)
    finished: bool = False
    winner: str | None = None


def apply_event(vm: MatchVM, ev: Event, god_view: bool) -> MatchVM:
    """应用单个事件到 ViewModel（纯函数，返回新 VM）。"""
    p = ev.payload
    next_vm = MatchVM(
        phase=vm.phase, day=vm.day, label=vm.label,
        feed=list(vm.feed), seats=list(vm.seats),
        finished=vm.finished, winner=vm.winner,
    )

    # 阶段事件
    if ev.type == "phase.started":
        phase = str(p.get("phase", ""))
        next_vm.phase = "night" if phase.startswith("night") or phase in ("wolf_meeting", "seer_check", "witch_turn", "night_resolve") else "day"
        next_vm.day = int(p.get("day", ev.day_index))
        next_vm.label = PHASE_LABELS.get(phase, phase)

    # 发言类
    elif ev.type == "player.speech":
        next_vm.feed.append({"type": "speech", "speaker": p.get("seat"), "text": p.get("text", "")})

    elif ev.type == "player.last_words":
        next_vm.feed.append({"type": "last_words", "speaker": p.get("seat"), "text": p.get("text", "")})

    elif ev.type == "player.monologue":
        if god_view:  # 上帝视角才显示独白
            next_vm.feed.append({"type": "monologue", "speaker": p.get("seat"), "text": p.get("text", "")})

    elif ev.type == "channel.message":
        next_vm.feed.append({"type": "channel", "speaker": p.get("seat"), "text": p.get("text", "")})

    # 夜晚操作
    elif ev.type == "night.kill_target":
        target = p.get("target", 0)
        if not target:  # 引擎空刀可能是 0 或 null（decided_by=empty），都显示为空刀
            next_vm.feed.append({"type": "system", "text": "狼队空刀"})
        else:
            next_vm.feed.append({"type": "system", "text": f"狼队选择击杀 {target}号"})

    elif ev.type == "night.resolved":
        dead = p.get("dead", [])
        if not dead:
            next_vm.feed.append({"type": "system", "text": "昨夜平安夜"})
        else:
            seats = "、".join(f"{s}号" for s in dead)
            next_vm.feed.append({"type": "system", "text": f"昨夜死亡：{seats}"})

    # 投票
    elif ev.type == "vote.cast":
        seat = p.get("seat", 0)
        target = p.get("target", 0)
        if target == 0:
            next_vm.feed.append({"type": "vote", "speaker": seat, "text": f"{seat}号 弃票"})
        else:
            next_vm.feed.append({"type": "vote", "speaker": seat, "text": f"{seat}号 投票给 {target}号"})

    # 对局结束
    elif ev.type == "match.finished":
        next_vm.finished = True
        next_vm.winner = p.get("winner")

    return next_vm
