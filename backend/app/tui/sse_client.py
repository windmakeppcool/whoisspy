"""SSE 客户端：连接后端流、去重、重连。"""

from __future__ import annotations

import asyncio
import json
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
        """SSE 流 URL（带 last_event_id 游标，与前端 EventSource 重连一致）。"""
        url = f"{self.base_url}/api/matches/{self.match_id}/stream?view={self.view}"
        if self.last_seq > 0:
            url += f"&last_event_id={self.last_seq}"
        return url

    def should_process(self, event: dict[str, Any]) -> bool:
        """检查事件是否应该处理（按 seq 去重）。"""
        seq = event.get("seq", 0)
        if seq <= self.last_seq:
            return False
        self.last_seq = seq
        return True

    def _reconnect_headers(self) -> dict[str, str]:
        """重连时的 HTTP headers（兼容 Last-Event-ID 约定）。"""
        headers: dict[str, str] = {}
        if self.last_seq > 0:
            headers["Last-Event-ID"] = str(self.last_seq)
        return headers

    def _reconnect_delay(self, attempt: int) -> float:
        """重连延迟（指数退避，上限 30 秒）。"""
        delay = min(2 ** attempt, 30)
        return float(delay)

    async def connect(self) -> None:
        """建立 SSE 连接。"""
        self._client = httpx.AsyncClient(timeout=None)
        self._connected = True

    async def disconnect(self) -> None:
        """断开连接。"""
        self._connected = False  # 先置位，通知重试循环退出
        if self._client:
            await self._client.aclose()
            self._client = None

    async def events(self) -> AsyncGenerator[dict[str, Any], None]:
        """接收事件流（异步生成器，断线指数退避自动重连）。

        - 建连/读流出错 → `_reconnect_delay` 退避后重连，游标经 last_event_id 查询参数续传；
        - 收到 `event: match_finished` → 对局结束，停止重连；
        - disconnect() 后退出循环。
        """
        if not self._client:
            await self.connect()

        attempt = 0
        while self._connected and self._client is not None:
            match_finished = False
            try:
                # 每次重连重新取 URL（last_seq 已随事件推进）
                async with self._client.stream(
                    "GET", self.stream_url, headers=self._reconnect_headers()
                ) as response:
                    response.raise_for_status()
                    attempt = 0  # 建连成功，退避计数归零

                    async for line in response.aiter_lines():
                        if line.startswith("event: match_finished"):
                            match_finished = True
                            break
                        if line.startswith("data: "):
                            data = line[6:]
                            try:
                                event = json.loads(data)
                                if self.should_process(event):
                                    yield event
                            except json.JSONDecodeError:
                                continue
            except (httpx.HTTPError, OSError):
                if not self._connected:
                    break  # 主动断开引发的错误，直接退出

            if match_finished or not self._connected:
                break

            # 指数退避后重连
            await asyncio.sleep(self._reconnect_delay(attempt))
            attempt += 1
