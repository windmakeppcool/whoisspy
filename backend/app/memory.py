"""事件 → 座位记忆行（agent 记忆层唯一渲染，docs/backend/06-prompts.md）。

「本座可见的事件必须有落点」——尤其票型、警徽归属、开枪结果（决定推理质量）。
他人发言一律围栏包裹并净化（防注入）；按可见性过滤后交给 agent 拼装。
"""

from __future__ import annotations

from typing import Any

from app.events import Event


def _sanitize(text: str) -> str:
    """围栏净化：尖括号转全角（围栏不可被内容闭合）、行首 # 转全角（无法伪造 prompt 段落）。"""
    text = text.replace("<", "＜").replace(">", "＞")
    lines = []
    for line in text.split("\n"):
        stripped = line.lstrip("#")
        if stripped != line:
            line = "＃" * (len(line) - len(stripped)) + stripped
        lines.append(line)
    return "\n".join(lines)


def _fence(seat_no: int, text: str) -> str:
    return f'<speech seat="{seat_no}">{_sanitize(text)}</speech>'


def _seats(seats) -> str:
    return "、".join(f"{int(s)} 号" for s in sorted(seats or []))


def memory_line(event: Event) -> str | None:
    """单条事件 → 记忆行；None = 该事件不进记忆（刻意不落点清单见 06-prompts 四）。"""
    t, p = event.type, event.payload
    if t in ("player.speech", "channel.message", "player.last_words"):
        text = str(p.get("text", ""))
        if t == "player.last_words":
            text = f"（遗言）{text}"
        return _fence(int(p.get("seat") or 0), text)
    if t == "phase.started":
        phase = str(p.get("phase", ""))
        return f"【第 {int(p.get('day', event.day_index))} 天·{p.get('label') or phase}】"
    if t == "day.speech_order":
        order = p.get("order") or []
        return ("本轮发言顺序：" + "→".join(f"{int(s)} 号" for s in order) + "。"
                if order else None)
    if t == "match.started":
        return "对局开始。"
    if t == "match.finished":
        camp = "狼人阵营" if p.get("winner") == "wolf" else "好人阵营"
        return f"对局结束：{camp}获胜（{p.get('reason', '')}）。"
    if t == "night.resolved":
        deaths = p.get("deaths") or {}
        if not deaths:
            return f"第 {event.day_index} 夜：平安夜，无人死亡。"
        return f"第 {event.day_index} 夜：{_seats(deaths)} 死亡。"
    if t == "night.seer_result":
        verdict = "狼人" if p.get("verdict") == "wolf" else "好人"
        return f"你查验了 {p.get('target')} 号玩家：阵营是【{verdict}】。"
    if t == "vote.cast":
        seat_no, target = int(p.get("seat") or 0), int(p.get("target") or 0)
        return f"{seat_no} 号弃票。" if not target else f"{seat_no} 号投给了 {target} 号。"
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
        return ("上警报名：" + "、".join(f"{int(s)} 号" for s in seats) + "。"
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


def _visible_to(vis: Any, seat: int) -> bool:
    """该座位是否可见此事件（与事件落库的 vis 一致）。"""
    if vis.level == "public":
        return True
    if vis.level == "seat":
        return seat in (vis.seats or [])
    return False  # god：仅上帝视角


def memory_for_seat(events: list[Event], seat: int) -> list[str]:
    """该座位可见的事件历史投影（记忆层，append-only 逐事件渲染）。"""
    lines: list[str] = []
    for ev in events:
        if not _visible_to(ev.vis, seat):
            continue
        line = memory_line(ev)
        if line:
            lines.append(line)
    return lines