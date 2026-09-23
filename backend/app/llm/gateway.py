"""LLM 网关：OpenAI 兼容统一接入 + MockLLM + 重试/修复链 + 用量记录。

容错链（docs/engine.md）：网络/5xx 重试≤2 → 坏 JSON 一次修复调用 → 上层兜底。
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from typing import Any, Protocol

from openai import AsyncOpenAI

from app.agents.protocol import parse_agent_response

DEFAULT_TIMEOUT_S = 60.0
DEFAULT_RETRY_DELAYS = (2.0, 5.0)  # 仅网络/超时类错误重试


class _Inner(Protocol):
    async def complete(self, *, base_url: str, api_key: str, model: str,
                       messages: list[dict[str, str]], purpose: str) -> str: ...


class UsageSink(Protocol):
    async def record_call(self, **kw: Any) -> None: ...


class MockLLM:
    """剧本驱动的假 LLM：按 script 依次返回；支持故障注入（bad_json/timeout）。"""

    def __init__(self, script: list[dict[str, Any]], fail_rate: float = 0.0,
                 rng_seed: int = 0, fail_mode: str = "bad_json"):
        self._script = [json.dumps(s, ensure_ascii=False) if isinstance(s, dict) else s
                        for s in script]
        self._fail_rate = fail_rate
        self._rng = random.Random(rng_seed)
        self._fail_mode = fail_mode
        self.calls: list[dict[str, Any]] = []

    async def complete(self, *, base_url: str, api_key: str, model: str,
                       messages: list[dict[str, str]], purpose: str) -> str:
        self.calls.append({"purpose": purpose, "model": model, "n_messages": len(messages)})
        if self._rng.random() < self._fail_rate:
            if self._fail_mode == "timeout":
                raise TimeoutError("mock timeout")
            return "这不是JSON{{{"
        if self._script:
            return self._script.pop(0)
        return json.dumps({"speech": "", "monologue": "", "action": None}, ensure_ascii=False)

    async def ask_json(self, *, base_url: str, api_key: str, model: str,
                       messages: list[dict[str, str]], purpose: str,
                       match_id: int = 0) -> dict[str, Any]:
        """与 OpenAICompatGateway 同接口：Mock 不做重试/修复，失败如实抛出。"""
        raw = await self.complete(base_url=base_url, api_key=api_key, model=model,
                                  messages=messages, purpose=purpose)
        return parse_agent_response(raw)


class OpenAICompatGateway:
    """生产网关：inner 可注入（测试用假实现），默认 openai SDK。

    ask_json 完成「重试 → 一次格式修复 → 抛出」链条，并把每次尝试记录进 usage_sink。
    兜底动作由 engine/faults.py 决定，本层只负责把失败如实上抛。
    """

    def __init__(self, inner: _Inner | None = None, usage_sink: UsageSink | None = None,
                 retry_delays: tuple[float, ...] = DEFAULT_RETRY_DELAYS,
                 timeout_s: float = DEFAULT_TIMEOUT_S):
        self._inner = inner
        self._sink = usage_sink
        self._retry_delays = retry_delays
        self._timeout_s = timeout_s
        self._clients: dict[tuple[str, str], AsyncOpenAI] = {}

    def _client(self, base_url: str, api_key: str) -> AsyncOpenAI:
        key = (base_url, api_key)
        client = self._clients.get(key)
        if client is None:
            client = AsyncOpenAI(base_url=base_url, api_key=api_key or "EMPTY",
                                 timeout=self._timeout_s, max_retries=0)
            self._clients[key] = client
        return client

    async def _raw_complete(self, *, base_url: str, api_key: str, model: str,
                            messages: list[dict[str, str]], purpose: str,
                            match_id: int = 0) -> str:
        t0 = time.monotonic()
        status, prompt_tokens, completion_tokens, err = "ok", 0, 0, None
        try:
            if self._inner is not None:
                out = await self._inner.complete(base_url=base_url, api_key=api_key,
                                                 model=model, messages=messages, purpose=purpose)
                status = "ok"
            else:
                resp = await self._client(base_url, api_key).chat.completions.create(
                    model=model, messages=messages, temperature=0.7)  # type: ignore[arg-type]
                out = resp.choices[0].message.content or ""
                usage = getattr(resp, "usage", None)
                prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
                completion_tokens = getattr(usage, "completion_tokens", 0) or 0
        except (asyncio.TimeoutError, TimeoutError):
            status, err = "timeout", "timeout"
            raise
        except Exception as e:  # 网络/5xx/其它
            status, err = "error", str(e)
            raise
        finally:
            if self._sink is not None:
                await self._sink.record_call(
                    match_id=match_id, purpose=purpose, model=model,
                    prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                    cost_micros=0, latency_ms=int((time.monotonic() - t0) * 1000),
                    status=status,
                )
        return out

    async def ask_json(self, *, base_url: str, api_key: str, model: str,
                       messages: list[dict[str, str]], purpose: str,
                       match_id: int = 0) -> dict[str, Any]:
        """带容错链的 JSON 请求。彻底失败抛最后一个异常。"""
        last_err: Exception | None = None
        raw = ""
        for attempt, delay in enumerate((None, *self._retry_delays)):
            if delay:
                await asyncio.sleep(delay)
            try:
                raw = await self._raw_complete(base_url=base_url, api_key=api_key,
                                               model=model, messages=messages, purpose=purpose,
                                               match_id=match_id)
                return parse_agent_response(raw)
            except (ConnectionError, asyncio.TimeoutError, TimeoutError) as e:
                last_err = e  # 网络/超时：重试
            except ValueError as e:
                # 坏 JSON：一次格式修复调用
                fix_messages = [*messages,
                                {"role": "assistant", "content": raw},
                                {"role": "user", "content":
                                 "你的上一条输出不是合法 JSON。请只输出一个 JSON 对象，"
                                 "结构：{\"speech\": str, \"monologue\": str, \"action\": dict|null}。"}]
                try:
                    raw2 = await self._raw_complete(base_url=base_url, api_key=api_key,
                                                    model=model, messages=fix_messages,
                                                    purpose=f"{purpose}/fix", match_id=match_id)
                    return parse_agent_response(raw2)
                except ValueError as e2:
                    raise ValueError(f"格式修复仍失败: {e2}") from e2
        assert last_err is not None
        raise last_err
