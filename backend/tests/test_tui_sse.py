"""SSE 客户端测试：连接、事件流、去重、重连。"""

import asyncio
import httpx
import pytest
from unittest.mock import MagicMock
from app.tui.sse_client import SSEClient


class _FakeResponse:
    """模拟 httpx 响应：只提供 TUI 用到的接口。"""

    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    def raise_for_status(self) -> None:
        """模拟 200 OK。"""
        return None

    async def aiter_lines(self):
        """逐行产出 SSE 文本。"""
        for line in self._lines:
            yield line


class _FakeStreamCM:
    """模拟 httpx stream() 返回的异步上下文管理器。

    result 为 Exception 时在 __aenter__ 抛出（模拟建连失败）。
    """

    def __init__(self, result) -> None:
        self._result = result

    async def __aenter__(self):
        if isinstance(self._result, Exception):
            raise self._result
        return self._result

    async def __aexit__(self, *args) -> bool:
        return False


@pytest.mark.asyncio
async def test_sse客户端初始化():
    """验证 SSEClient 可以创建。"""
    client = SSEClient(base_url="http://localhost:8000", match_id=1, view="god")
    assert client.base_url == "http://localhost:8000"
    assert client.match_id == 1
    assert client.view == "god"
    assert client.last_seq == 0


@pytest.mark.asyncio
async def test_sse去重():
    """验证按 seq 去重。"""
    client = SSEClient(base_url="http://localhost:8000", match_id=1, view="god")

    # 模拟收到重复 seq
    ev1 = {"seq": 1, "type": "match.created", "payload": {}}
    ev1_dup = {"seq": 1, "type": "match.created", "payload": {}}
    ev2 = {"seq": 2, "type": "match.started", "payload": {}}

    assert client.should_process(ev1) == True
    assert client.should_process(ev1_dup) == False  # 重复
    assert client.should_process(ev2) == True
    assert client.last_seq == 2


@pytest.mark.asyncio
async def test_sse断线重连参数():
    """验证断线重连时携带 Last-Event-ID。"""
    client = SSEClient(base_url="http://localhost:8000", match_id=1, view="god")
    client.last_seq = 42

    # 验证重连 headers 包含 Last-Event-ID
    headers = client._reconnect_headers()
    assert headers.get("Last-Event-ID") == "42"


@pytest.mark.asyncio
async def test_sse重连延迟():
    """验证重连延迟递增（指数退避）。"""
    client = SSEClient(base_url="http://localhost:8000", match_id=1, view="god")

    assert client._reconnect_delay(0) == 1.0  # 第一次：1秒
    assert client._reconnect_delay(1) == 2.0  # 第二次：2秒
    assert client._reconnect_delay(2) == 4.0  # 第三次：4秒
    assert client._reconnect_delay(10) == 30.0  # 上限：30秒


@pytest.mark.asyncio
async def test_sse流URL带last_event_id游标():
    """服务端读 last_event_id 查询参数（与前端一致），游标需拼进 URL。"""
    client = SSEClient(base_url="http://localhost:8000", match_id=7, view="god")
    assert "last_event_id" not in client.stream_url  # 首连不带游标

    client.last_seq = 5
    assert "last_event_id=5" in client.stream_url
    assert "view=god" in client.stream_url


@pytest.mark.asyncio
async def test_sse断线自动重连并续传():
    """首次建连失败 → 指数退避后重连成功并产出事件（此前 events() 无重试循环）。"""
    client = SSEClient(base_url="http://http-down", match_id=1, view="god")
    client.last_seq = 3
    client._reconnect_delay = lambda attempt: 0.0  # 测试免等待

    calls: list[str] = []

    def fake_stream(method: str, url: str, headers=None):
        calls.append(url)
        if len(calls) == 1:
            return _FakeStreamCM(httpx.ConnectError("connection refused"))
        return _FakeStreamCM(_FakeResponse(
            ['data: {"seq": 4, "type": "match.started", "payload": {}}']))

    client._client = MagicMock()
    client._client.stream = fake_stream
    client._connected = True

    gen = client.events()
    ev = await gen.__anext__()
    await gen.aclose()

    assert ev["seq"] == 4
    assert len(calls) == 2  # 第一次失败 + 第二次成功
    assert "last_event_id=3" in calls[1]  # 重连带游标续传


@pytest.mark.asyncio
async def test_sse收到match_finished后停止重连():
    """对局结束帧后停止重连（避免对局完成后无限重连、TUI 无法自然退出）。"""
    client = SSEClient(base_url="http://x", match_id=1, view="god")
    client._reconnect_delay = lambda attempt: 0.0

    calls: list[str] = []

    def fake_stream(method: str, url: str, headers=None):
        calls.append(url)
        return _FakeStreamCM(_FakeResponse(
            ['event: match_finished', 'data: {}']))

    client._client = MagicMock()
    client._client.stream = fake_stream
    client._connected = True

    gen = client.events()
    try:
        # 有限时等待：无停止逻辑则无限重连挂起 → TimeoutError 失败
        await asyncio.wait_for(gen.__anext__(), timeout=0.5)
        raise AssertionError("应自然结束而非产出事件")
    except StopAsyncIteration:
        pass
    finally:
        await gen.aclose()

    assert len(calls) == 1  # 收到结束后未重连
