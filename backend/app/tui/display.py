"""终端渲染：纯函数，输入 VM 返回字符串。"""

from __future__ import annotations

from app.tui.viewmodel import MatchVM


def render_header(vm: MatchVM, god_view: bool) -> str:
    """渲染头部（阶段指示 + 视角标识）。"""
    view_label = "上帝视角" if god_view else "沉浸视角"

    if vm.phase == "idle" and vm.day == 0:
        phase_text = "等待开局"
    else:
        phase_text = f"第{vm.day}天 · {vm.label}"

    return f"[{view_label}] {phase_text}"


def render_feed(vm: MatchVM) -> str:
    """渲染对话流。"""
    if not vm.feed:
        return "等待事件..."

    lines = []
    for item in vm.feed:
        item_type = item.get("type", "")
        speaker = item.get("speaker")
        text = item.get("text", "")

        if item_type == "system":
            lines.append(f"  [系统] {text}")
        elif item_type == "vote":
            lines.append(f"  [投票] {text}")
        elif speaker:
            lines.append(f"  {speaker}号: {text}")
        else:
            lines.append(f"  {text}")

    return "\n".join(lines)


def render_seats(vm: MatchVM, god_view: bool) -> str:
    """渲染座次表。"""
    if not vm.seats:
        return "座次表: -"

    parts = []
    for seat in vm.seats:
        seat_num = seat.get("seat", "?")
        alive = seat.get("alive", True)
        role = seat.get("role", "")
        status = "✓" if alive else "✗"
        role_str = f"({role})" if god_view and role else ""
        parts.append(f"{seat_num}{status}{role_str}")

    return "座次表: " + " ".join(parts)
