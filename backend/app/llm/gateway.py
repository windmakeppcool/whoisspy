"""LLM 网关：OpenAI 兼容统一接入 + MockLLM + 重试/修复链 + 用量记录。

容错链（docs/engine.md）：网络/5xx 重试≤2 → 坏 JSON 一次修复调用 → 上层兜底。
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from typing import Any, Protocol

import openai
from openai import AsyncOpenAI

from app.agents.protocol import parse_agent_response

DEFAULT_TIMEOUT_S = 60.0
DEFAULT_RETRY_DELAYS = (2.0, 5.0)  # 仅网络/超时/限流/5xx 类错误重试

# 可重试异常：必须显式列出 openai SDK 的异常类型——
# APIConnectionError / APITimeoutError / RateLimitError / InternalServerError
# 都不继承内置 ConnectionError/TimeoutError（实测 openai 3.x），
# 只捕内置异常会导致生产路径「一次都不重试」（历史 bug）。
_RETRYABLE_ERRORS: tuple[type[BaseException], ...] = (
    ConnectionError, TimeoutError,
    openai.APIConnectionError, openai.APITimeoutError,
    openai.RateLimitError, openai.InternalServerError,
)


def _is_timeout(err: BaseException) -> bool:
    """是否超时类错误（用于 usage 的 status 归类）。"""
    return isinstance(err, (asyncio.TimeoutError, TimeoutError, openai.APITimeoutError))


def _is_retryable(err: BaseException) -> bool:
    """网络/超时/限流/5xx 可重试；4xx 参数错、鉴权失败不重试。"""
    if isinstance(err, _RETRYABLE_ERRORS):
        return True
    return isinstance(err, openai.APIStatusError) and (
        err.status_code == 429 or err.status_code >= 500)


def _usage_get(obj: Any, name: str) -> Any:
    """从 usage 取字段：兼容对象与 dict 两种响应形态，无则 None。"""
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def parse_usage_tokens(usage: Any) -> dict[str, int]:
    """解析兼容端点 usage 为统一三项：prompt / completion / cached_prompt_tokens。

    缓存字段各家命名不同：OpenAI 系在 prompt_tokens_details.cached_tokens，
    DeepSeek 系是顶层 prompt_cache_hit_tokens。都取不到则视作全量未命中（cached=0）。
    """
    def _int(v: Any) -> int:
        return v if isinstance(v, int) and not isinstance(v, bool) else 0

    if usage is None:
        return {"prompt_tokens": 0, "completion_tokens": 0, "cached_prompt_tokens": 0}
    cached = (_int(_usage_get(_usage_get(usage, "prompt_tokens_details"), "cached_tokens"))
              or _int(_usage_get(usage, "prompt_cache_hit_tokens")))
    return {
        "prompt_tokens": _int(_usage_get(usage, "prompt_tokens")),
        "completion_tokens": _int(_usage_get(usage, "completion_tokens")),
        "cached_prompt_tokens": cached,
    }


def compute_cost_micros(tokens: dict[str, int], *, price_in: float = 0.0,
                        price_out: float = 0.0, price_cached_in: float | None = None) -> int:
    """按模型单价折算费用（单位：百万分之一货币单位，如「微元」）。

    单价定义：price_* = 每 1,000,000 token 的价格（providers.json 的 price_per_mtok_*）。
    T 个 token 的费用 = T × price / 1e6 货币单位 = T × price 微单位。
    缓存命中价缺省与输入价相同（未配置时不高估也不低估，如实按输入价计）。
    """
    cached = int(tokens.get("cached_prompt_tokens", 0) or 0)
    prompt = int(tokens.get("prompt_tokens", 0) or 0)
    completion = int(tokens.get("completion_tokens", 0) or 0)
    cached_price = price_in if price_cached_in is None else price_cached_in
    uncached = max(prompt - cached, 0)
    return int(round(uncached * price_in + cached * cached_price + completion * price_out))


class _Inner(Protocol):
    async def complete(self, *, base_url: str, api_key: str, model: str,
                       messages: list[dict[str, str]], purpose: str) -> str: ...


class UsageSink(Protocol):
    async def record_call(self, **kw: Any) -> None: ...


class MockLLM:
    """剧本驱动的假 LLM：按 script 依次返回；耗尽后回落启发式对话（保证 demo 局有内容）。

    支持故障注入（bad_json/timeout）；usage_sink 可选（估算 token 入账）。
    """

    def __init__(self, script: list[dict[str, Any]], fail_rate: float = 0.0,
                 rng_seed: int = 0, fail_mode: str = "bad_json",
                 usage_sink: UsageSink | None = None):
        self._script = [json.dumps(s, ensure_ascii=False) if isinstance(s, dict) else s
                        for s in script]
        self._fail_rate = fail_rate
        self._rng = random.Random(rng_seed)
        self._fail_mode = fail_mode
        self._sink = usage_sink
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
        return json.dumps(_heuristic_reply(messages, purpose, self._rng), ensure_ascii=False)

    async def ask_json(self, *, base_url: str, api_key: str, model: str,
                       messages: list[dict[str, str]], purpose: str,
                       match_id: int = 0, price_in: float = 0.0, price_out: float = 0.0,
                       price_cached_in: float | None = None) -> dict[str, Any]:
        """与 OpenAICompatGateway 同接口：Mock 不做重试/修复，失败如实抛出。"""
        raw = await self.complete(base_url=base_url, api_key=api_key, model=model,
                                  messages=messages, purpose=purpose)
        if self._sink is not None:
            pt = sum(len(m.get("content", "")) for m in messages) // 4
            tokens = {"prompt_tokens": pt, "completion_tokens": len(raw) // 4,
                      "cached_prompt_tokens": 0}
            await self._sink.record_call(
                match_id=match_id, purpose=purpose, model=model,
                prompt_tokens=tokens["prompt_tokens"],
                completion_tokens=tokens["completion_tokens"],
                cached_prompt_tokens=0,
                cost_micros=compute_cost_micros(tokens, price_in=price_in,
                                                price_out=price_out,
                                                price_cached_in=price_cached_in),
                latency_ms=1, status="ok")
        return parse_agent_response(raw)


def _heuristic_reply(messages: list[dict[str, str]], purpose: str,
                     rng: random.Random) -> dict[str, Any]:
    """从 prompt 反解出座位/动作类型/候选，产出确定性、有内容的回复。

    选目标策略：候选中非自己的最小座位（保证全桌一致 → 必然出人命/必然出警）。
    """
    import re

    content = messages[0].get("content", "") if messages else ""
    m_seat = re.search(r"你是 (\d+) 号座位", content)
    seat = int(m_seat.group(1)) if m_seat else 1
    m_type = re.search(r'"type": "([a-z_]+)"', content)
    atype = m_type.group(1) if m_type else "speech"
    m_cand = re.search(r"合法目标座位：\[([\d, ]+)\]", content)
    cands = [int(x) for x in m_cand.group(1).split(",")] if m_cand else []
    others = [c for c in sorted(set(cands)) if c != seat]
    target = others[0] if others else 0

    speech_templates = {
        "vote": f"{seat}号：我这票先给 {target} 号，他的发言漏洞最多，欢迎来验。",
        "kill": f"狼队友们，我倾向刀 {target} 号。",
        "check": f"今晚验 {target} 号。",
        "speech": f"我是 {seat} 号。目前信息有限，我先表个水：重点听 {target} 号和后面的人发言，谁急谁可疑。",
        "last_words": f"我是好人走的，{seat} 号平民一个，别被带节奏，剩下的人好好盘。",
        "register": f"{seat} 号上警：我来带队，这轮听我归。",
        "sheriff_speech": f"{seat} 号竞选宣言：我逻辑清楚敢归票，投我警徽稳。",
    }
    speech = speech_templates.get(atype, f"{seat}号发言。")
    if purpose == "channel":
        speech = f"狼队友们，我倾向刀 {target} 号。"
    if purpose == "sheriff_speech":
        speech = speech_templates["sheriff_speech"]

    action: dict[str, Any] | None
    if atype == "speech" and not cands:
        action = None
    elif atype == "register":
        action = {"type": "register", "yes": seat % 2 == 1}
    elif atype == "save":
        action = {"type": "save", "target": 0}
    elif atype == "badge":
        action = {"type": "badge", "target": target}
    elif cands:
        action = {"type": atype, "target": target}
    else:
        action = {"type": atype, "target": 0}

    return {
        "monologue": f"（内心）候选 {others or cands or '无'}，选 {target}。",
        "speech": speech,
        "action": action,
    }


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
                            match_id: int = 0, price_in: float = 0.0,
                            price_out: float = 0.0,
                            price_cached_in: float | None = None) -> str:
        t0 = time.monotonic()
        status, err = "ok", None
        tokens = {"prompt_tokens": 0, "completion_tokens": 0, "cached_prompt_tokens": 0}
        try:
            if self._inner is not None:
                out = await self._inner.complete(base_url=base_url, api_key=api_key,
                                                 model=model, messages=messages, purpose=purpose)
                status = "ok"
            else:
                resp = await self._client(base_url, api_key).chat.completions.create(
                    model=model, messages=messages, temperature=0.7)  # type: ignore[arg-type]
                out = resp.choices[0].message.content or ""
                tokens = parse_usage_tokens(getattr(resp, "usage", None))
        except _RETRYABLE_ERRORS as e:
            status, err = "timeout" if _is_timeout(e) else "error", str(e)
            raise
        except Exception as e:  # 其它（参数错/鉴权失败等）：重试无意义
            status, err = "error", str(e)
            raise
        finally:
            if self._sink is not None:
                await self._sink.record_call(
                    match_id=match_id, purpose=purpose, model=model,
                    prompt_tokens=tokens["prompt_tokens"],
                    completion_tokens=tokens["completion_tokens"],
                    cached_prompt_tokens=tokens["cached_prompt_tokens"],
                    cost_micros=compute_cost_micros(tokens, price_in=price_in,
                                                    price_out=price_out,
                                                    price_cached_in=price_cached_in),
                    latency_ms=int((time.monotonic() - t0) * 1000),
                    status=status,
                )
        return out

    async def ask_json(self, *, base_url: str, api_key: str, model: str,
                       messages: list[dict[str, str]], purpose: str,
                       match_id: int = 0, price_in: float = 0.0, price_out: float = 0.0,
                       price_cached_in: float | None = None) -> dict[str, Any]:
        """带容错链的 JSON 请求。

        链路（docs/engine.md）：网络/超时/限流/5xx 重试 ≤2（退避 2s/5s）；
        坏 JSON 每个原始响应只做**一次**格式修复调用，修复仍不合法即抛（走上层中性兜底）。
        彻底失败抛最后一个异常。
        """
        last_err: Exception | None = None
        raw = ""
        for attempt, delay in enumerate((None, *self._retry_delays)):
            if delay:
                await asyncio.sleep(delay)
            try:
                raw = await self._raw_complete(base_url=base_url, api_key=api_key,
                                               model=model, messages=messages, purpose=purpose,
                                               match_id=match_id, price_in=price_in,
                                               price_out=price_out,
                                               price_cached_in=price_cached_in)
                return parse_agent_response(raw)
            except ValueError as e:
                # 坏 JSON：一次格式修复调用
                fix_messages = [*messages,
                                {"role": "assistant", "content": raw},
                                {"role": "user", "content":
                                 "你的上一条输出不是合法 JSON。请只输出一个 JSON 对象，"
                                 "结构：{\"monologue\": str, \"speech\": str, \"action\": dict|null}。"}]
                try:
                    raw2 = await self._raw_complete(base_url=base_url, api_key=api_key,
                                                    model=model, messages=fix_messages,
                                                    purpose=f"{purpose}/fix", match_id=match_id,
                                                    price_in=price_in, price_out=price_out,
                                                    price_cached_in=price_cached_in)
                    return parse_agent_response(raw2)
                except ValueError as e2:
                    # 修复也拿不到合法 JSON：按契约走兜底（不再消耗外层重试次数）
                    raise ValueError(f"格式修复仍失败: {e2}") from e2
                except Exception as e2:
                    if not _is_retryable(e2):
                        raise
                    last_err = e2  # 修复调用撞上网络/5xx：交给外层重试
            except Exception as e:
                if not _is_retryable(e):
                    raise  # 参数错/鉴权失败等，重试没有意义
                last_err = e
        assert last_err is not None
        raise last_err
