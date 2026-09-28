"""LLM 网关（docs/backend/08-llm.md）：mock 确定性 + 真实重试 + 计量 + trace。"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from openai import (
    APIConnectionError,
    APITimeoutError,
    APIError,
    AsyncOpenAI,
    InternalServerError,
    RateLimitError,
)

_RETRYABLE_EXC = (APIConnectionError, APITimeoutError, RateLimitError, InternalServerError)
TIMEOUT_S = 60.0  # 单次调用超时
MAX_ATTEMPTS = 3  # 初始 + 重试 ≤2
BACKOFF_S = (2.0, 5.0)  # 退避 2s/5s


class LLMFailure(Exception):
    """重试耗尽后的调用失败（由 agent 层记 player.fallback）。"""


@dataclass
class LLMReply:
    """一次成功调用的结果。"""

    raw: str
    usage: dict[str, int]  # {prompt_tokens, completion_tokens, cached_prompt_tokens}
    cost_micros: int
    latency_ms: int
    status: str = "ok"


class TraceRecorder:
    """--trace 的 JSONL 记录器（每局一个文件，逐条 flush，跑挂了也可用）。"""

    def __init__(self, path: str) -> None:
        self._fp = open(path, "w", encoding="utf-8")

    def write(self, obj: dict[str, Any]) -> None:
        self._fp.write(json.dumps(obj, ensure_ascii=False) + "\n")
        self._fp.flush()

    def close(self) -> None:
        self._fp.close()


class LLMGateway:
    """按座位的 model 分派：mock（确定性）或 openai 兼容真实调用。

    record: async (match_id, seat, purpose, model, tokens..., cost_micros,
                   latency_ms, status) -> None（store 落 llm_call）。
    trace: TraceRecorder | None（--trace 开启时注入）。
    """

    def __init__(self, *,
                 record: Callable[..., Awaitable[None]] | None = None,
                 trace: TraceRecorder | None = None) -> None:
        self._record = record
        self._trace = trace

    async def complete(self, *, seat_cfg: dict[str, Any], messages: list[dict[str, str]],
                       purpose: str, match_id: int) -> LLMReply:
        started = time.monotonic()
        if seat_cfg.get("model") == "mock":
            reply = _mock_complete(messages)
        else:
            reply = await self._real_complete(seat_cfg, messages)
        reply.latency_ms = int((time.monotonic() - started) * 1000)
        if self._record is not None:
            await self._record(match_id=match_id, seat=seat_cfg.get("seat", 0),
                               purpose=purpose, model=seat_cfg.get("model", ""),
                               **reply.usage, cost_micros=reply.cost_micros,
                               latency_ms=reply.latency_ms, status=reply.status)
        if self._trace is not None:
            self._trace.write({"t": "call", "seat": seat_cfg.get("seat", 0),
                               "purpose": purpose, "model": seat_cfg.get("model", ""),
                               "messages": messages, "raw": reply.raw,
                               "usage": reply.usage, "cost_micros": reply.cost_micros,
                               "latency_ms": reply.latency_ms, "status": reply.status})
        return reply

    # ---------- 真实调用 ----------

    async def _real_complete(self, seat_cfg: dict[str, Any],
                             messages: list[dict[str, str]]) -> LLMReply:
        client = AsyncOpenAI(base_url=seat_cfg.get("base_url", ""),
                             api_key=seat_cfg.get("api_key", ""), timeout=TIMEOUT_S)

        async def do_call():
            resp = await client.chat.completions.create(
                model=seat_cfg.get("model", ""), messages=messages)
            return resp

        resp = await _call_with_retry(do_call)
        raw = (resp.choices[0].message.content or "") if resp.choices else ""
        usage = parse_usage_tokens(getattr(resp, "usage", None))
        cost = compute_cost_micros(
            usage,
            price_in=float(seat_cfg.get("price_per_mtok_in", 0.0) or 0.0),
            price_out=float(seat_cfg.get("price_per_mtok_out", 0.0) or 0.0),
            price_cached_in=seat_cfg.get("price_per_mtok_cached_in"))
        return LLMReply(raw=raw, usage=usage, cost_micros=cost, latency_ms=0)


# ---------- 重试 ----------

async def _call_with_retry(do_call, *, attempts: int = MAX_ATTEMPTS,
                           backoff: tuple[float, ...] = BACKOFF_S):
    """重试语义（S4/D28.3）：openai 连接/超时/限流/5xx 可重试，退避递增；4xx 不重试。"""
    last: Exception | None = None
    for i in range(attempts):
        try:
            return await do_call()
        except _RETRYABLE_EXC as e:
            last = e
        except APIError as e:
            code = e.status_code
            if code and (code == 429 or code >= 500):
                last = e
            else:
                raise
        if i < attempts - 1:
            await asyncio.sleep(backoff[min(i, len(backoff) - 1)])
    raise LLMFailure(str(last)) from last


# ---------- mock provider（确定性，P3） ----------

_RE_SEAT = re.compile(r"你是 (\d+) 号座位")
_RE_TYPE = re.compile(r"动作类型：([a-z_]+)")
_RE_CAND = re.compile(r"合法目标座位：\[([\d, ]+)\]")


def _mock_complete(messages: list[dict[str, str]]) -> LLMReply:
    """从 prompt 反解座位/动作类型/候选，产出确定性、有内容的回复（同 prompt 必得同回复）。"""
    content = messages[0].get("content", "") if messages else ""
    m_seat = _RE_SEAT.search(content)
    m_type = _RE_TYPE.search(content)
    m_cand = _RE_CAND.search(content)
    seat = int(m_seat.group(1)) if m_seat else 0
    atype = m_type.group(1) if m_type else "pass"
    cands = ([int(c.strip()) for c in m_cand.group(1).split(",") if c.strip().isdigit()]
             if m_cand else [])

    if atype == "register":
        action: dict[str, Any] = {"type": "register", "yes": seat in (3, 6, 9)}
    elif atype == "speech":
        action = {"type": "speech", "target": 0}
    elif cands:
        action = {"type": atype, "target": cands[(seat * 3 + 5) % len(cands)]}
    else:
        action = {"type": atype, "target": 0}

    raw = json.dumps({
        "monologue": f"(mock) {seat} 号按 {atype} 行动",
        "speech": f"我是 {seat} 号，{atype} 环节发言（mock）。",
        "action": action,
    }, ensure_ascii=False)
    pt = sum(len(m.get("content", "")) for m in messages) // 4
    return LLMReply(raw=raw,
                    usage={"prompt_tokens": pt, "completion_tokens": len(raw) // 4,
                           "cached_prompt_tokens": 0},
                    cost_micros=0, latency_ms=0)


# ---------- 用量计量与计费 ----------

def parse_usage_tokens(usage: Any) -> dict[str, int]:
    """归一各家 usage 命名：OpenAI 系 prompt_tokens_details.cached_tokens、
    DeepSeek 系顶层 prompt_cache_hit_tokens；取不到按 0（全量未命中）。
    """
    if usage is None:
        return {"prompt_tokens": 0, "completion_tokens": 0, "cached_prompt_tokens": 0}
    details = getattr(usage, "prompt_tokens_details", None) or {}
    cached = (_int(getattr(details, "cached_tokens", 0))
              or _int(getattr(usage, "prompt_cache_hit_tokens", 0)))
    return {
        "prompt_tokens": _int(getattr(usage, "prompt_tokens", 0)),
        "completion_tokens": _int(getattr(usage, "completion_tokens", 0)),
        "cached_prompt_tokens": cached,
    }


def compute_cost_micros(tokens: dict[str, int], *, price_in: float, price_out: float,
                        price_cached_in: float | None = None) -> int:
    """费用（微元）：未命中输入价 + 命中缓存价 + 输出价；单价 = 每百万 token。

    cached > prompt 时按 0 计未命中（防死负数）。
    """
    cached = int(tokens.get("cached_prompt_tokens", 0) or 0)
    prompt = int(tokens.get("prompt_tokens", 0) or 0)
    completion = int(tokens.get("completion_tokens", 0) or 0)
    cached_in = price_cached_in if price_cached_in is not None else price_in
    uncached = max(prompt - cached, 0)
    return round(uncached * price_in + cached * cached_in + completion * price_out)


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0