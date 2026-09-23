"""TUI 主循环测试。"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.tui.main import run_tui


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
