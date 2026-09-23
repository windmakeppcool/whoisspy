"""TUI 入口：事件循环、键盘交互、渲染。"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from app.core import Event, VisMeta
from app.tui.sse_client import SSEClient
from app.tui.viewmodel import MatchVM, apply_event
from app.tui.display import render_header, render_feed, render_seats


def handle_key(key: str) -> str | None:
    """键盘事件映射。"""
    if key in ("q", "\x03"):  # q 或 Ctrl+C
        return "quit"
    elif key == "g":
        return "toggle_view"
    return None


class Debouncer:
    """事件防抖器：100ms 内合并多次渲染。"""

    def __init__(self, interval: float = 0.1) -> None:
        self.interval = interval
        self._last_render = 0.0

    def should_render(self) -> bool:
        """是否应该渲染。"""
        now = time.monotonic()
        if now - self._last_render >= self.interval:
            self._last_render = now
            return True
        return False


def _dict_to_event(raw: dict[str, Any]) -> Event:
    """SSE 原始 dict → Event（SSE 客户端产出 dict，apply_event 需要 Event）。

    保留 vis 字段：沉浸视角按 vis.level 过滤的依据（缺省 public 兼容旧帧）。
    """
    vis_raw = raw.get("vis") or {}
    vis = VisMeta(
        level=vis_raw.get("level", "public"),
        seats=list(vis_raw.get("seats") or []),
    )
    return Event(
        type=str(raw.get("type", "")),
        payload=raw.get("payload") or {},
        day_index=int(raw.get("day_index", 0)),
        phase=str(raw.get("phase", "")),
        vis=vis,
        seq=int(raw.get("seq", 0)),
    )


async def run_tui(base_url: str, match_id: int) -> None:
    """运行 TUI 主循环。"""
    from rich.console import Console

    console = Console()
    client = SSEClient(base_url=base_url, match_id=match_id, view="god")
    vm = MatchVM()
    god_view = True
    debouncer = Debouncer(interval=0.1)
    running = True

    def render() -> None:
        """渲染当前状态。"""
        header = render_header(vm, god_view)
        seats = render_seats(vm, god_view)
        feed = render_feed(vm)
        console.clear()
        console.print(f"[bold cyan]{header}[/bold cyan]")
        console.print(f"[yellow]{seats}[/yellow]")
        console.print("-" * 60)
        console.print(feed)
        console.print("\n[dim]按 q 退出，g 切换视角[/dim]")

    try:
        await client.connect()

        # 并行运行：事件接收 + 键盘输入
        async def event_loop() -> None:
            nonlocal vm
            async for raw in client.events():
                vm = apply_event(vm, _dict_to_event(raw), god_view)
                if debouncer.should_render():
                    render()

        async def keyboard_loop() -> None:
            nonlocal god_view, running
            import sys
            while running:
                # 简化版：从 stdin 读取（生产环境用 textual）
                key = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: sys.stdin.read(1)
                )
                action = handle_key(key)
                if action == "quit":
                    running = False
                elif action == "toggle_view":
                    god_view = not god_view
                    render()

        # 同时运行两个循环：任一结束（如按 q 退出）即取消另一个
        tasks = [asyncio.create_task(event_loop()), asyncio.create_task(keyboard_loop())]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        # 传播已完成任务中的异常（KeyboardInterrupt 由外层捕获）
        for task in done:
            exc = task.exception()
            if exc is not None:
                raise exc

    except KeyboardInterrupt:
        pass
    finally:
        await client.disconnect()
        console.print("[dim]TUI 已退出[/dim]")
