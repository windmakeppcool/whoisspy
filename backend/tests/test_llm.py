"""LLM 网关测试（Red 先行）：docs/backend/08-llm.md 全规格。"""

import asyncio
import json

import httpx
import pytest
from openai import APIConnectionError, APITimeoutError, BadRequestError, RateLimitError

from app.llm import (
    LLMFailure,
    LLMGateway,
    TraceRecorder,
    _call_with_retry,
    compute_cost_micros,
    parse_usage_tokens,
)

PROMPT = (
    "【总览】规则。\n你是 3 号座位。你的角色：villager。\n"
    "## 当前任务\n投票：投出你最怀疑的玩家（0 为弃权）。\n"
    "动作类型：vote\n合法目标座位：[1, 2, 3, 4]\n"
    "输出格式（只输出一个合法 JSON 对象）…"
)


def _cfg(**kw):
    cfg = {"seat": 3, "role": "villager", "model": "mock", "base_url": "",
           "api_key": "", "price_per_mtok_in": 0.0, "price_per_mtok_out": 0.0}
    cfg.update(kw)
    return cfg


# ---------- mock 确定性 ----------

async def test_mock同prompt同回复():
    gw = LLMGateway()
    r1 = await gw.complete(seat_cfg=_cfg(), messages=[{"role": "user", "content": PROMPT}],
                           purpose="vote", match_id=1)
    r2 = await gw.complete(seat_cfg=_cfg(), messages=[{"role": "user", "content": PROMPT}],
                           purpose="vote", match_id=1)
    assert r1.raw == r2.raw
    assert r1.usage == r2.usage


async def test_mock反解动作与候选():
    gw = LLMGateway()
    r = await gw.complete(seat_cfg=_cfg(), messages=[{"role": "user", "content": PROMPT}],
                          purpose="vote", match_id=1)
    data = json.loads(r.raw)
    assert data["action"]["type"] == "vote"
    assert data["action"]["target"] in (1, 2, 3, 4)
    assert "3 号" in data["monologue"]
    assert r.usage["prompt_tokens"] > 0
    assert r.cost_micros == 0


async def test_mock_register与speech分支():
    gw = LLMGateway()
    reg_prompt = (PROMPT.replace("动作类型：vote", "动作类型：register")
                  .replace("合法目标座位：[1, 2, 3, 4]", ""))
    r = await gw.complete(seat_cfg=_cfg(), messages=[{"role": "user", "content": reg_prompt}],
                          purpose="register", match_id=1)
    assert json.loads(r.raw)["action"] == {"type": "register", "yes": True}  # prompt 是 3 号
    reg1 = reg_prompt.replace("你是 3 号座位", "你是 1 号座位")
    r = await gw.complete(seat_cfg=_cfg(), messages=[{"role": "user", "content": reg1}],
                          purpose="register", match_id=1)
    assert json.loads(r.raw)["action"] == {"type": "register", "yes": False}


# ---------- usage 归一与计费 ----------

def test_usage归一OpenAI形态():
    from types import SimpleNamespace

    u = SimpleNamespace(prompt_tokens=1000, completion_tokens=50,
                        prompt_tokens_details=SimpleNamespace(cached_tokens=400))
    assert parse_usage_tokens(u) == {"prompt_tokens": 1000, "completion_tokens": 50,
                                     "cached_prompt_tokens": 400}


def test_usage归一DeepSeek形态():
    from types import SimpleNamespace

    u = SimpleNamespace(prompt_tokens=800, completion_tokens=20,
                        prompt_cache_hit_tokens=512)
    assert parse_usage_tokens(u) == {"prompt_tokens": 800, "completion_tokens": 20,
                                     "cached_prompt_tokens": 512}


def test_usage归一缺失按全量未命中():
    assert parse_usage_tokens(None) == {"prompt_tokens": 0, "completion_tokens": 0,
                                        "cached_prompt_tokens": 0}


def test_cost计算():
    tokens = {"prompt_tokens": 1000, "completion_tokens": 100,
              "cached_prompt_tokens": 400}
    # 600×2 + 400×0.5 + 100×8 = 1200 + 200 + 800 = 2200 微元
    assert compute_cost_micros(tokens, price_in=2.0, price_out=8.0, price_cached_in=0.5) == 2200


def test_cost缺省缓存价等于输入价():
    tokens = {"prompt_tokens": 1000, "completion_tokens": 0, "cached_prompt_tokens": 1000}
    assert compute_cost_micros(tokens, price_in=2.0, price_out=8.0) == 2000


def test_cost缓存多于prompt不死负():
    tokens = {"prompt_tokens": 100, "completion_tokens": 0, "cached_prompt_tokens": 999}
    assert compute_cost_micros(tokens, price_in=2.0, price_out=0.0) == 1998


# ---------- 重试语义 ----------

def _req():
    return httpx.Request("POST", "http://x")


async def test_重试成功路径():
    calls = []

    async def do():
        calls.append(1)
        if len(calls) < 3:
            raise APIConnectionError(request=_req())
        return "ok"

    assert await _call_with_retry(do, backoff=(0.01, 0.01)) == "ok"
    assert len(calls) == 3  # 初始 + 2 次重试


async def test_重试耗尽抛LLMFailure():
    async def do():
        raise APITimeoutError(request=_req())

    with pytest.raises(LLMFailure):
        await _call_with_retry(do, backoff=(0.01, 0.01))


async def test_4xx不重试():
    async def do():
        raise BadRequestError(message="bad", response=httpx.Response(400, request=_req()),
                              body=None)

    with pytest.raises(BadRequestError):
        await _call_with_retry(do, backoff=(0.01, 0.01))


async def test_429限流重试():
    calls = []

    async def do():
        calls.append(1)
        if len(calls) < 2:
            raise RateLimitError(message="limit", response=httpx.Response(429, request=_req()),
                                 body=None)
        return "ok"

    assert await _call_with_retry(do, backoff=(0.01, 0.01)) == "ok"
    assert len(calls) == 2


# ---------- trace 落盘 ----------

async def test_trace落盘schema(tmp_path):
    trace = TraceRecorder(str(tmp_path / "m.jsonl"))
    gw = LLMGateway(trace=trace)
    await gw.complete(seat_cfg=_cfg(), messages=[{"role": "user", "content": PROMPT}],
                      purpose="vote", match_id=7)
    trace.write({"t": "event", "event": {"type": "x"}})
    trace.close()
    lines = (tmp_path / "m.jsonl").read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    call = json.loads(lines[0])
    assert call["t"] == "call"
    assert call["seat"] == 3 and call["purpose"] == "vote"
    assert call["messages"][0]["content"] == PROMPT
    assert call["raw"]
    ev = json.loads(lines[1])
    assert ev["t"] == "event"


async def test_record回调收到计量():
    seen = []

    async def record(**kw):
        seen.append(kw)

    gw = LLMGateway(record=record)
    await gw.complete(seat_cfg=_cfg(), messages=[{"role": "user", "content": PROMPT}],
                      purpose="vote", match_id=9)
    assert len(seen) == 1
    rec = seen[0]
    assert rec["match_id"] == 9 and rec["seat"] == 3 and rec["model"] == "mock"
    assert rec["status"] == "ok"
    assert rec["cost_micros"] == 0