"""渲染逻辑：事件流 → 分段对话 JSON。

按 day_index + phase 分段，段内提取关键事件渲染成 entries。
上帝视角内容（含狼队频道、独白、夜晚操作）由上游 view=god 过滤保证。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.core import Event

# 段落标签映射：(day_index, is_night) → 中文标签
_CN_NUM = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]


def _day_label(day_index: int, is_night: bool) -> str:
    """生成段落标签：第一夜 / 第一天 / 第二天 ..."""
    if day_index <= 0:
        day_index = 1
    if day_index < len(_CN_NUM):
        num = _CN_NUM[day_index]
    else:
        num = str(day_index)
    return f"第{num}{'夜' if is_night else '天'}"


def _is_night_phase(phase: str) -> bool:
    """判断是否夜晚阶段。"""
    return phase in ("night", "night_resolve") or "night" in phase


def _seat_str(seat: int | None) -> str | None:
    """座位号 → 显示字符串。"""
    if seat is None or seat == 0:
        return None
    return f"{seat}号"


def _render_entry(event: Event) -> dict[str, Any] | None:
    """单个事件 → entry dict；返回 None 表示跳过。"""
    etype = event.type
    p = event.payload

    # 发言类
    if etype == "player.speech":
        return {"speaker": _seat_str(p.get("seat")), "type": "speech",
                "text": p.get("text", "")}
    if etype == "player.last_words":
        return {"speaker": _seat_str(p.get("seat")), "type": "last_words",
                "text": p.get("text", "")}
    if etype == "player.monologue":
        return {"speaker": _seat_str(p.get("seat")), "type": "monologue",
                "text": p.get("text", "")}
    if etype == "channel.message":
        return {"speaker": _seat_str(p.get("seat")), "type": "channel",
                "text": p.get("text", "")}

    # 系统事件（夜晚操作、投票、死讯等）
    if etype == "night.kill_target":
        target = p.get("target", 0)
        if target == 0 or p.get("decided_by") == "no_wolf":
            return {"speaker": None, "type": "system", "text": "狼队空刀"}
        return {"speaker": None, "type": "system",
                "text": f"狼队选择击杀 {_seat_str(target)}"}
    if etype == "night.guard_target":
        target = p.get("target", 0)
        if target == 0:
            return {"speaker": None, "type": "system", "text": "守卫空守"}
        return {"speaker": None, "type": "system",
                "text": f"守卫守护 {_seat_str(target)}"}
    if etype == "night.seer_query":
        return {"speaker": None, "type": "system",
                "text": f"预言家查验 {_seat_str(p.get('target'))}"}
    if etype == "night.seer_result":
        verdict = p.get("verdict", "")
        verdict_cn = "好人" if verdict in ("good", "villager") else "狼人"
        return {"speaker": None, "type": "system",
                "text": f"预言家查验 {_seat_str(p.get('target'))} 为 {verdict_cn}"}
    if etype == "night.witch_action":
        action = p.get("act", p.get("action", ""))
        if action == "save":
            return {"speaker": None, "type": "system", "text": "女巫使用解药"}
        if action == "poison":
            return {"speaker": None, "type": "system",
                    "text": f"女巫使用毒药毒杀 {_seat_str(p.get('target'))}"}
        return {"speaker": None, "type": "system", "text": "女巫不用药"}
    if etype == "night.resolved":
        deaths = p.get("deaths") or {k: "kill" for k in (p.get("dead") or [])}
        if not deaths:
            return {"speaker": None, "type": "system", "text": "昨夜平安夜"}
        seats = "、".join(_seat_str(int(s)) for s in deaths)
        return {"speaker": None, "type": "system", "text": f"昨夜死亡：{seats}"}

    # 投票
    if etype == "vote.cast":
        seat = _seat_str(p.get("seat"))
        target = p.get("target", 0)
        if target == 0:
            return {"speaker": seat, "type": "vote", "text": f"{seat} 弃票"}
        return {"speaker": seat, "type": "vote",
                "text": f"{seat} 投票给 {_seat_str(target)}"}
    if etype == "vote.resolved":
        exiled = p.get("exiled", 0)
        if exiled == 0:
            return {"speaker": None, "type": "system", "text": "本轮平票，无人被放逐"}
        return {"speaker": None, "type": "system",
                "text": f"投票结果：{_seat_str(exiled)} 被放逐"}

    # 开枪
    if etype == "gun.shoot":
        seat = _seat_str(p.get("seat"))
        target = p.get("target", 0)
        text = p.get("text", "")
        if target == 0:
            return {"speaker": seat, "type": "system",
                    "text": f"{seat} 开枪但未选择目标" + (f"：{text}" if text else "")}
        return {"speaker": seat, "type": "system",
                "text": f"{seat} 开枪带走 {_seat_str(target)}" + (f"：{text}" if text else "")}

    # 警长
    if etype == "sheriff.badge":
        action = p.get("action", "")
        if action == "transfer":
            return {"speaker": None, "type": "system",
                    "text": f"警徽移交给 {_seat_str(p.get('to'))}"}
        if action == "destroy":
            return {"speaker": None, "type": "system", "text": "警徽撕毁"}
        return None

    # 阶段边界（可选：生成分隔提示）
    if etype == "phase.started":
        return {"speaker": None, "type": "phase",
                "text": f"—— {p.get('phase', event.phase)} 开始 ——"}
    if etype == "phase.ended":
        return {"speaker": None, "type": "phase",
                "text": f"—— {p.get('phase', event.phase)} 结束 ——"}

    # 其他事件跳过
    return None


def render_dialog(*, match_id: int, game_type: str,
                  events: list[Event]) -> dict[str, Any]:
    """渲染事件流为分段对话 JSON。

    Args:
        match_id: 对局 ID
        game_type: 游戏类型（werewolf 等）
        events: 已按 seq 排序的事件列表（上游应已做 view=god 过滤）

    Returns:
        分段对话 dict，含 match_id / game_type / exported_at / segments
    """
    # 按 (day_index, is_night) 分段
    segments: list[dict[str, Any]] = []
    current_key: tuple[int, bool] | None = None
    current_seg: dict[str, Any] | None = None

    for ev in events:
        is_night = _is_night_phase(ev.phase)
        key = (ev.day_index, is_night)

        if key != current_key:
            # 新段
            label = _day_label(ev.day_index, is_night)
            current_seg = {
                "label": label,
                "day_index": ev.day_index,
                "phase": ev.phase,
                "entries": [],
            }
            segments.append(current_seg)
            current_key = key

        entry = _render_entry(ev)
        if entry is not None and current_seg is not None:
            current_seg["entries"].append(entry)

    return {
        "match_id": match_id,
        "game_type": game_type,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "segments": segments,
    }
