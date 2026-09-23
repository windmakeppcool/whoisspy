"""SSE 客户端测试：连接、事件流、去重、重连。"""

import asyncio
import pytest
from app.tui.sse_client import SSEClient


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
