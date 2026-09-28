"""事件 → 观赛文案行（present 唯一权威，docs/backend/11-export.md）。

导出 JSON 与 CLI 终端直播共用本模块；客户端/导出不得自带事件解释逻辑。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.events import Event


@dataclass
class Line:
    """一条观赛行（kind: speech/last_words/monologue/channel/system/vote/phase）。"""

    kind: str
    seat: int | None
    text: str


def _seat_str(seat: int | None) -> str:
    return "未知座位" if seat in (None, 0) else f"{seat} 号"


def present(event: Event) -> Line | None:
    """单条事件 → 观赛行；None = 不上屏。"""
    t, p = event.type, event.payload
    if t == "phase.started":
        phase = str(p.get("phase", ""))
        return Line("phase", None,
                    f"—— {p.get('label') or phase}（第 {int(p.get('day', event.day_index))} 天）——")
    if t == "player.speech":
        return Line("speech", int(p.get("seat") or 0), f"{_seat_str(p.get('seat'))}：{p.get('text', '')}")
    if t == "player.last_words":
        return Line("last_words", int(p.get("seat") or 0),
                    f"{_seat_str(p.get('seat'))}（遗言）：{p.get('text', '')}")
    if t == "channel.message":
        return Line("channel", int(p.get("seat") or 0),
                    f"{_seat_str(p.get('seat'))}（狼队频道）：{p.get('text', '')}")
    if t == "player.monologue":
        return Line("monologue", int(p.get("seat") or 0),
                    f"{_seat_str(p.get('seat'))}（内心）：{p.get('text', '')}")
    if t == "night.kill_target":
        target = p.get("target")
        if not target or p.get("decided_by") == "no_wolf":
            return Line("system", None, "狼队空刀")
        return Line("system", None, f"狼队选择击杀 {target} 号")
    if t == "night.seer_query":
        target = p.get("target")
        return Line("system", None,
                    "预言家今晚未查验" if not target else f"预言家查验 {target} 号")
    if t == "night.seer_result":
        verdict = "狼人" if p.get("verdict") == "wolf" else "好人"
        return Line("system", None, f"查验 {p.get('target')} 号：{verdict}")
    if t == "night.witch_action":
        act = p.get("act")
        if act == "save":
            return Line("system", None, "女巫使用解药")
        if act == "poison":
            return Line("system", None, f"女巫毒杀 {p.get('target')} 号")
        return Line("system", None, "女巫不用药")
    if t == "night.resolved":
        deaths = p.get("deaths") or {}
        if not deaths:
            return Line("system", None,
                        f"第 {int(p.get('day', event.day_index))} 夜：平安夜")
        seats = "、".join(f"{int(s)} 号" for s in sorted(deaths))
        return Line("system", None, f"第 {int(p.get('day', event.day_index))} 夜：{seats} 死亡")
    if t == "night.death_cause":
        causes = p.get("causes") or {}
        parts = [f"{int(s)} 号={'刀杀' if c == 'knife' else '毒杀'}"
                 for s, c in sorted(causes.items())]
        return Line("system", None, f"死因：{'、'.join(parts)}")
    if t == "skill_state.notice":
        return Line("system", int(p.get("seat") or 0),
                    f"{_seat_str(p.get('seat'))}猎人："
                    + ("可以开枪" if p.get("can_shoot") else "今晚不能开枪"))
    if t == "sheriff.registered":
        seats = p.get("seats") or []
        return Line("system", None,
                    ("上警：" + "、".join(f"{int(s)} 号" for s in seats))
                    if seats else "无人上警")
    if t == "sheriff.badge":
        if p.get("action") == "transfer":
            return Line("system", None, f"{p.get('to')} 号当选警长")
        return Line("system", None, "警徽被撕毁")
    if t == "day.speech_order":
        order = p.get("order") or []
        return Line("system", None, "发言顺序：" + "→".join(f"{int(s)}" for s in order) + " 号"
                    if order else None)
    if t == "vote.cast":
        seat_no = int(p.get("seat") or 0)
        target = p.get("target") or 0
        return Line("vote", seat_no,
                    f"{_seat_str(seat_no)}弃票" if not target
                    else f"{_seat_str(seat_no)}投票给 {_seat_str(target)}")
    if t == "vote.resolved":
        if p.get("scope") == "sheriff":
            return Line("system", None,
                        "警长投票平票" if p.get("tie")
                        else f"{p.get('exiled')} 号当选警长")
        return Line("system", None,
                    "平票，无人出局" if p.get("tie")
                    else f"{p.get('exiled')} 号被放逐出局")
    if t == "gun.shoot":
        seat_no = int(p.get("seat") or 0)
        target = p.get("target") or 0
        return Line("system", seat_no,
                    f"{_seat_str(seat_no)}放弃开枪" if not target
                    else f"{_seat_str(seat_no)}开枪带走 {_seat_str(target)}")
    if t == "player.fallback":
        return Line("system", int(p.get("seat") or 0),
                    f"⚠ {_seat_str(p.get('seat'))}调用失败走兜底（{p.get('reason', '')}）")
    if t == "rule.error":
        return Line("system", None, f"⚠ 规则异常（{p.get('phase', '')}）：{p.get('reason', '')}")
    if t == "match.finished":
        camp = "狼人阵营" if p.get("winner") == "wolf" else "好人阵营"
        return Line("system", None, f"🏁 对局结束：{camp}获胜（{p.get('reason', '')}）")
    if t == "match.stopped":
        return Line("system", None, f"⏹ 对局终止：{p.get('reason', '')}")
    if t == "role.dealt":
        return Line("system", int(p.get("seat") or 0),
                    f"发牌：{p.get('seat')} 号 = {p.get('role', '')}")
    return None  # match.created/started、night.started、channel.round.* 等不上屏