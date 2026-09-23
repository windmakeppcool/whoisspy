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
