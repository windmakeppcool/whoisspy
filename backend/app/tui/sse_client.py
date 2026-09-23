"""SSE 客户端：连接后端流、去重、重连。"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncGenerator

import httpx


class SSEClient:
    """SSE 流客户端。"""

    def __init__(self, base_url: str, match_id: int, view: str = "god") -> None:
        self.base_url = base_url.rstrip("/")
        self.match_id = match_id
        self.view = view
        self.last_seq = 0
        self._client: httpx.AsyncClient | None = None
        self._connected = False

    @property
    def stream_url(self) -> str:
        """SSE 流 URL。"""
        return f"{self.base_url}/api/matches/{self.match_id}/stream?view={self.view}"

    def should_process(self, event: dict[str, Any]) -> bool:
        """检查事件是否应该处理（按 seq 去重）。"""
        seq = event.get("seq", 0)
        if seq <= self.last_seq:
            return False
        self.last_seq = seq
        return True

    async def connect(self) -> None:
        """建立 SSE 连接。"""
        self._client = httpx.AsyncClient(timeout=None)
        self._connected = True

    async def disconnect(self) -> None:
        """断开连接。"""
        if self._client:
            await self._client.aclose()
            self._client = None
        self._connected = False

    async def events(self) -> AsyncGenerator[dict[str, Any], None]:
        """接收事件流（异步生成器）。"""
        if not self._client:
            await self.connect()

        assert self._client is not None

        # 带 Last-Event-ID 重连
        headers = {}
        if self.last_seq > 0:
            headers["Last-Event-ID"] = str(self.last_seq)

        async with self._client.stream(
            "GET", self.stream_url, headers=headers
        ) as response:
            response.raise_for_status()

            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    import json
                    data = line[6:]
                    try:
                        event = json.loads(data)
                        if self.should_process(event):
                            yield event
                    except json.JSONDecodeError:
                        continue
