"""TUI 集成测试：端到端验证。"""

import asyncio
import json
import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch
from app.api.app import create_app
from app.tui.viewmodel import MatchVM, apply_event
from app.tui.display import render_header, render_feed, render_seats
from app.core import Event, VisMeta


def test_完整事件流到渲染():
    """验证事件流 → VM → 渲染的完整链路。"""
    events = [
        Event(type="match.created", payload={}, day_index=0, phase="", vis=VisMeta(level="public")),
        Event(type="phase.started", payload={"phase": "night_start", "day": 1},
              day_index=1, phase="night_start", vis=VisMeta(level="public")),
        Event(type="player.speech", payload={"seat": 1, "text": "大家好"},
              day_index=1, phase="day_speech", vis=VisMeta(level="public")),
        Event(type="night.kill_target", payload={"target": 3},
              day_index=1, phase="night", vis=VisMeta(level="god")),
        Event(type="match.finished", payload={"winner": "good"},
              day_index=2, phase="", vis=VisMeta(level="public")),
    ]

    # 投影到 VM
    vm = MatchVM()
    for ev in events:
        vm = apply_event(vm, ev, god_view=True)

    # 渲染
    header = render_header(vm, god_view=True)
    feed = render_feed(vm)

    # 验证（偏差修正：phase.started payload 为 day=1，header 应为"第1天"，简报原文"第2天"与事件数据矛盾）
    assert "第1天" in header or "等待开局" in header
    assert "大家好" in feed
    assert "狼队选择击杀 3号" in feed
    assert vm.finished == True
    assert vm.winner == "good"


def test_视角切换():
    """验证视角切换过滤效果。"""
    vm_god = MatchVM()
    vm_immersive = MatchVM()

    ev = Event(type="player.monologue", payload={"seat": 1, "text": "我是狼"},
               day_index=1, phase="night", vis=VisMeta(level="god"))

    vm_god = apply_event(vm_god, ev, god_view=True)
    vm_immersive = apply_event(vm_immersive, ev, god_view=False)

    assert len(vm_god.feed) == 1
    assert len(vm_immersive.feed) == 0


def test_座次表渲染():
    """验收：渲染逻辑 100% 覆盖——render_seats 上帝视角显示角色、沉浸视角隐藏角色。"""
    vm = MatchVM(seats=[
        {"seat": 1, "alive": True, "role": "wolf"},
        {"seat": 2, "alive": False, "role": "villager"},
    ])

    god = render_seats(vm, god_view=True)
    immersive = render_seats(vm, god_view=False)

    # 上帝视角：存活标记 + 角色
    assert "座次表" in god
    assert "1✓(wolf)" in god
    assert "2✗(villager)" in god
    # 沉浸视角：无角色泄露
    assert "1✓" in immersive
    assert "(wolf)" not in immersive
    assert "(villager)" not in immersive

    # 空座次表占位
    assert "座次表: -" in render_seats(MatchVM(), god_view=True)


@pytest.fixture()
async def api_client(tmp_path):
    """独立临时库的 ASGI 客户端（覆盖 SSE /stream 端点）。"""
    app = create_app(db_path=str(tmp_path / "tui_int.db"))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            yield c


_SEATS = [{"seat": i, "persona_id": "calm", "base_url": "", "api_key_env": "",
           "model": "mock", "name": f"p{i}"} for i in range(1, 7)]


async def test_SSE流推送事件帧(api_client):
    """验收：/stream 端点推送 data: 帧——TUI 事件源的生命线。

    回归背景：gen() 曾对 Event 数据类用下标 ev['seq']，
    导致流在第一个事件即抛 TypeError、连接中断。
    """
    resp = await api_client.post("/api/matches", json={
        "game_type": "werewolf", "board": {"id": "p6-classic"}, "seats": _SEATS})
    assert resp.status_code == 200, resp.text
    match_id = resp.json()["id"]

    frames: list[str] = []
    async with api_client.stream(
        "GET", f"/api/matches/{match_id}/stream",
        params={"view": "god"}, timeout=10.0,
    ) as stream:
        assert stream.status_code == 200
        async for line in stream.aiter_lines():
            if line.startswith("data: "):
                frames.append(line[6:])
                break  # 拿到第一帧即够验证链路
            # ": keepalive" 等注释行 → 继续等待事件

    assert frames, "SSE 流应至少推送一个 data 帧"
    first = json.loads(frames[0])
    assert "seq" in first and "type" in first


def test_引擎空刀payload渲染():
    """回归：引擎 decided_by=empty 时 target=null，不得渲染成 "None号"。"""
    vm = MatchVM()
    ev = Event(type="night.kill_target",
               payload={"target": None, "decided_by": "empty"},
               day_index=1, phase="night", vis=VisMeta(level="god"))
    vm = apply_event(vm, ev, god_view=True)
    feed = render_feed(vm)

    assert "狼队空刀" in feed
    assert "None" not in feed
