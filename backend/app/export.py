"""对话导出（docs/backend/11-export.md）：事件 → 分段对话 JSON。

观赛文案唯一渲染处是 present.py（P5）；本模块只做视角过滤、分段与组装。
v2（11-export 五，前端展示契约）：段末 stage 快照（复用 state reducer 折算）、
结构化投票回合（tally 复用 rules 计票口径）、人设显示名、对局索引 index.json。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.events import Event
from app.present import present
from app.rules import tally_votes
from app.state import GameState

# 夜/昼归属（03-events 二）：警长竞选在夜末 → 归当夜
NIGHT_PHASES = {"night_start", "wolf_meeting", "seer_check", "witch_turn",
                "sheriff_elect", "night_resolve"}

_CN_NUM = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]


def _visible(ev: Event, view: str) -> bool:
    if view == "god":
        return True
    return ev.vis.level == "public"


def _seg_key(ev: Event) -> tuple[Any, ...]:
    """分段键：开局 / (day_index, is_night)。"""
    if ev.day_index <= 0:
        return ("open", 0)
    return (ev.day_index, ev.phase in NIGHT_PHASES)


def _seg_label(key) -> tuple[str, int, bool]:
    """分段键 → (label, day_index, is_night)。"""
    if key[0] == "open":
        return "开局", 0, False
    day, is_night = key
    num = _CN_NUM[day] if day < len(_CN_NUM) else str(day)
    return f"第{num}{'夜' if is_night else '天'}", day, is_night


def _fold_one(state: GameState, ev: Event) -> None:
    """折叠单条事件：role.dealt 播种 roles/alive（与 flow._deal 语义一致），
    其余走 apply。判死/警长只由 public 事件驱动 → 两视角快照一致、无泄漏。"""
    if ev.type == "role.dealt":
        seat_no = int(ev.payload.get("seat") or 0)
        state.roles[seat_no] = str(ev.payload.get("role", ""))
        state.alive[seat_no] = True
    else:
        state.apply(ev)


def _vote_round(ev: Event, state: GameState) -> dict[str, Any]:
    """vote.resolved → 结构化投票回合（tally 复用 rules.tally_votes 口径：警长 2 票）。"""
    p = ev.payload
    votes = {int(k): int(v) for k, v in (p.get("votes") or {}).items()}
    tally = tally_votes(votes, sheriff=state.sheriff)
    return {
        "title": str(p.get("title") or
                     ("警长投票" if p.get("scope") == "sheriff" else "放逐投票")),
        "scope": str(p.get("scope") or "exile"),
        "votes": votes,
        "tally": tally["counts"],
        "exiled": p.get("exiled"),
        "tie": bool(p.get("tie")),
    }


def _segments(events: list[Event], view: str) -> list[dict[str, Any]]:
    """分段（可见事件定界，保持事件序）+ 段末 stage 快照 + 段内投票回合。

    快照对**全量事件**（含视角外事件）折叠：角色/判死/警长是两视角公共事实，
    折叠结果与视角无关，杜绝「public 视角算不出死亡」。
    """
    segs: list[dict[str, Any]] = []
    bounds: list[tuple[int, int]] = []  # 每段在全量事件里的索引区间 [start, end]
    current: dict[str, Any] | None = None
    cur_start = 0
    for i, ev in enumerate(events):
        if not _visible(ev, view):
            continue
        key = _seg_key(ev)
        if current is None or current["_key"] != key:
            if current is not None:
                bounds.append((cur_start, i - 1))
            label, day, is_night = _seg_label(key)
            current = {"_key": key, "label": label, "day_index": day,
                       "is_night": is_night, "entries": []}
            segs.append(current)
            cur_start = i
        line = present(ev)
        if line is not None:
            current["entries"].append({"kind": line.kind, "seat": line.seat,
                                       "text": line.text})
    if current is not None:
        bounds.append((cur_start, len(events) - 1))

    state = GameState(roles={}, alive={})
    cursor = 0
    for seg, (start, end) in zip(segs, bounds):
        votes: list[dict[str, Any]] = []
        for i in range(cursor, end + 1):
            _fold_one(state, events[i])
            if events[i].type == "vote.resolved":
                votes.append(_vote_round(events[i], state))
        cursor = end + 1
        seg["stage"] = {"alive": sorted(s for s in state.alive if state.alive[s]),
                        "sheriff": state.sheriff}
        if votes:
            seg["votes"] = votes
    return [{k: v for k, v in s.items() if k != "_key"} for s in segs]


def build_export(*, match_id: int, match_info: dict[str, Any],
                 seats: list[dict[str, Any]], events: list[Event],
                 usage: dict[str, Any], view: str = "god",
                 personas: dict[str, dict[str, str]] | None = None) -> dict[str, Any]:
    """组装导出文档（11-export 三 + 五）。

    personas: {persona_id: {"name", "style"}}，可选；缺省回退 persona_id。
    """
    result = match_info.get("result") or {}
    seat_rows: list[dict[str, Any]] = []
    for s in seats:
        persona_id = s.get("persona_id", "")
        meta = (personas or {}).get(persona_id)
        seat_rows.append({
            "seat": s["seat"],
            "persona_id": persona_id,
            "persona_name": meta["name"] if meta else persona_id,
            "persona_style": meta["style"] if meta else s.get("style", ""),
            "model": s.get("model", ""),
        })
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


def index_entry(*, match_id: int, seed: int | None, status: str | None,
                winner: str | None, reason: str | None, player_count: int,
                exported_at: str, views: list[str]) -> dict[str, Any]:
    """对局索引条目（11-export 五.3）。"""
    return {
        "match_id": match_id,
        "seed": seed,
        "status": status,
        "winner": winner,
        "reason": reason,
        "player_count": player_count,
        "exported_at": exported_at,
        "views": sorted(views),
    }


def update_index(index_path: str | Path, entry: dict[str, Any]) -> None:
    """按 match_id 合并更新 exports/index.json（同局覆盖；views 取并集）。"""
    path = Path(index_path)
    doc: dict[str, Any] = {"generated_at": datetime.now(timezone.utc).isoformat(),
                           "matches": []}
    if path.exists():
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            doc = {"generated_at": doc["generated_at"], "matches": []}
    matches = doc.get("matches") or []
    mid = entry["match_id"]
    for m in matches:
        if m.get("match_id") == mid:
            old_views = set(m.get("views") or [])
            m.update(entry)
            m["views"] = sorted(old_views | set(entry["views"]))
            break
    else:
        matches.append(dict(entry))
    doc["matches"] = matches
    doc["generated_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")