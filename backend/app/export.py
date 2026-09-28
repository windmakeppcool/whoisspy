"""对话导出（docs/backend/11-export.md）：事件 → 分段对话 JSON。

观赛文案唯一渲染处是 present.py（P5）；本模块只做视角过滤、分段与组装。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.events import Event
from app.present import present

# 夜/昼归属（03-events 二）：警长竞选在夜末 → 归当夜
NIGHT_PHASES = {"night_start", "wolf_meeting", "seer_check", "witch_turn",
                "sheriff_elect", "night_resolve"}

_CN_NUM = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]


def _visible(ev: Event, view: str) -> bool:
    if view == "god":
        return True
    return ev.vis.level == "public"


def _segments(events: list[Event], view: str) -> list[dict[str, Any]]:
    """按 (day_index, is_night) 分段：开局 → 第一夜 → 第一天 → …（保持事件序）。"""
    segments: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for ev in events:
        if not _visible(ev, view):
            continue
        if ev.day_index <= 0:
            key = ("open", 0)
            label = "开局"
        else:
            is_night = ev.phase in NIGHT_PHASES
            num = _CN_NUM[ev.day_index] if ev.day_index < len(_CN_NUM) else str(ev.day_index)
            key = (ev.day_index, is_night)
            label = f"第{num}{'夜' if is_night else '天'}"
        if current is None or current["_key"] != key:
            current = {"_key": key, "label": label, "day_index": ev.day_index,
                       "entries": []}
            segments.append(current)
        line = present(ev)
        if line is not None:
            current["entries"].append({"kind": line.kind, "seat": line.seat,
                                       "text": line.text})
    return [{k: v for k, v in s.items() if k != "_key"} for s in segments]


def build_export(*, match_id: int, match_info: dict[str, Any],
                 seats: list[dict[str, Any]], events: list[Event],
                 usage: dict[str, Any], view: str = "god") -> dict[str, Any]:
    """组装导出文档（11-export 三）。"""
    result = match_info.get("result") or {}
    seat_rows = [{"seat": s["seat"], "persona_id": s.get("persona_id", ""),
                  "model": s.get("model", "")} for s in seats]
    if view == "god":
        for row, s in zip(seat_rows, seats):
            row["role"] = s.get("role")
    board = dict(match_info.get("board") or {})
    board.pop("model_assignments", None)
    return {
        "match_id": match_id,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "view": view,
        "match": {
            "seed": match_info.get("seed"),
            "status": match_info.get("status"),
            "winner": result.get("winner"),
            "reason": result.get("reason"),
            "board": board,
            "seats": seat_rows,
            "model_assignments": (match_info.get("board") or {}).get(
                "model_assignments", []),
        },
        "segments": _segments(events, view),
        "usage": {
            **usage,
            "fallbacks": sum(1 for e in events if e.type == "player.fallback"),
            "rule_errors": sum(1 for e in events if e.type == "rule.error"),
        },
    }