"""TUI 主循环测试。"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.tui.main import run_tui, _dict_to_event


@pytest.mark.asyncio
async def test_键盘事件映射():
    """验证键盘事件映射。"""
    from app.tui.main import handle_key

    # q 或 Ctrl+C → 退出
    assert handle_key("q") == "quit"
    assert handle_key("\x03") == "quit"  # Ctrl+C

    # g → 切换视角
    assert handle_key("g") == "toggle_view"

    # 其他键 → 忽略
    assert handle_key("x") is None


@pytest.mark.asyncio
async def test_事件防抖():
    """验证事件防抖（100ms 合并）。"""
    from app.tui.main import Debouncer

    debouncer = Debouncer(interval=0.1)
    assert debouncer.should_render() == True  # 第一次立即渲染

    # 快速连续调用
    assert debouncer.should_render() == False  # 100ms 内不渲染
    assert debouncer.should_render() == False

    # 等待 100ms 后
    await asyncio.sleep(0.11)
    assert debouncer.should_render() == True


def test_dict_to_event保留vis可见性():
    """验证 _dict_to_event 保留 vis 字段（沉浸过滤的依据）。"""
    raw = {"seq": 1, "type": "night.kill_target", "day_index": 1, "phase": "night",
           "payload": {"target": 3}, "vis": {"level": "god", "seats": []}}
    ev = _dict_to_event(raw)
    assert ev.vis.level == "god"
    assert ev.vis.seats == []

    raw_seat = {**raw, "vis": {"level": "seat", "seats": [1, 2]}}
    ev_seat = _dict_to_event(raw_seat)
    assert ev_seat.vis.level == "seat"
    assert ev_seat.vis.seats == [1, 2]


def test_dict_to_event缺省vis为public():
    """验证缺 vis 字段时默认 public（向后兼容）。"""
    raw = {"seq": 1, "type": "player.speech", "day_index": 1, "phase": "",
           "payload": {"seat": 1, "text": "hi"}}
    ev = _dict_to_event(raw)
    assert ev.vis.level == "public"
    assert ev.vis.seats == []
