"""用量计量测试（Red 先行，M6）：按 providers.json 单价折算 cost_micros。

回归背景：cost_micros 曾在生产路径恒为 0（用量面板「费用」永远是空的）。
"""

from types import SimpleNamespace

import pytest

from app.llm.gateway import MockLLM, OpenAICompatGateway, compute_cost_micros


class TestComputeCost:
    def test_按单价折算(self):
        tokens = {"prompt_tokens": 1000, "completion_tokens": 100,
                  "cached_prompt_tokens": 400}
        # 未命中 600×1.0 + 命中 400×0.5 + 输出 100×2.0 = 600+200+200 = 1000
        assert compute_cost_micros(tokens, price_in=1.0, price_out=2.0,
                                   price_cached_in=0.5) == 1000

    def test_未配置缓存价按输入价计(self):
        tokens = {"prompt_tokens": 1000, "completion_tokens": 0,
                  "cached_prompt_tokens": 1000}
        assert compute_cost_micros(tokens, price_in=3.0, price_out=0.0) == 3000

    def test_零单价为零(self):
        assert compute_cost_micros({"prompt_tokens": 10**6, "completion_tokens": 10**6},
                                   price_in=0.0, price_out=0.0) == 0

    def test_缺字段当零(self):
        assert compute_cost_micros({}, price_in=1.0, price_out=1.0) == 0

    def test_缓存token多于prompt不死负(self):
        tokens = {"prompt_tokens": 10, "completion_tokens": 0,
                  "cached_prompt_tokens": 99}
        assert compute_cost_micros(tokens, price_in=1.0) == 99


class FakeUsage:
    def __init__(self):
        self.prompt_tokens = 1000
        self.completion_tokens = 100
        self.prompt_tokens_details = SimpleNamespace(cached_tokens=400)


class FakeCompletions:
    async def create(self, **kw):
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content='{"speech": "hi", "action": null}'))],
            usage=FakeUsage())


class FakeClient:
    def __init__(self):
        self.chat = SimpleNamespace(completions=FakeCompletions())


class Sink:
    def __init__(self):
        self.calls: list[dict] = []

    async def record_call(self, **kw):
        self.calls.append(kw)


class TestGatewayCostRecording:
    async def test_记账带单价折算的费用(self, monkeypatch):
        sink = Sink()
        gw = OpenAICompatGateway(usage_sink=sink)
        monkeypatch.setattr(gw, "_client", lambda base_url, api_key: FakeClient())
        out = await gw.ask_json(base_url="https://x/v1", api_key="k", model="m",
                                messages=[{"role": "user", "content": "hi"}],
                                purpose="speech", match_id=7,
                                price_in=1.0, price_out=2.0, price_cached_in=0.5)
        assert out["speech"] == "hi"
        rec = sink.calls[0]
        assert (rec["prompt_tokens"], rec["completion_tokens"],
                rec["cached_prompt_tokens"]) == (1000, 100, 400)
        assert rec["cost_micros"] == 1000  # 与 compute_cost_micros 单测同口径
        assert rec["match_id"] == 7

    async def test_mock也不再把费用写成零(self):
        sink = Sink()
        llm = MockLLM(script=[{"speech": "a", "action": None}], usage_sink=sink)
        await llm.ask_json(base_url="", api_key="", model="mock",
                           messages=[{"role": "user", "content": "x" * 400}],
                           purpose="speech", match_id=1,
                           price_in=1.0, price_out=1.0)
        assert sink.calls[0]["cost_micros"] > 0


class TestRetryChain:
    """回归 S4：真实 SDK 异常必须被重试（不能只认内置 ConnectionError）。"""

    @pytest.mark.parametrize("exc_name", [
        "APIConnectionError", "APITimeoutError", "RateLimitError", "InternalServerError"])
    async def test_openai异常会重试(self, exc_name):
        import httpx
        import openai

        exc_cls = getattr(openai, exc_name)

        def make_exc() -> Exception:
            request = httpx.Request("POST", "https://x/v1/chat/completions")
            if issubclass(exc_cls, openai.APIStatusError):
                status = 429 if "RateLimit" in exc_name else 500
                response = httpx.Response(status, request=request)
                return exc_cls("boom", response=response, body=None)
            return exc_cls(request=request)

        calls = {"n": 0}

        class Inner:
            async def complete(self, **kw):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise make_exc()
                return '{"speech": "ok", "action": null}'

        gw = OpenAICompatGateway(inner=Inner(), retry_delays=(0.0, 0.0))
        out = await gw.ask_json(base_url="", api_key="", model="m", messages=[],
                                purpose="speech")
        assert out["speech"] == "ok"
        assert calls["n"] == 2, f"{exc_name} 应触发一次重试"

    async def test_参数错不重试(self):
        import httpx
        import openai

        calls = {"n": 0}
        request = httpx.Request("POST", "https://x/v1/chat/completions")
        response = httpx.Response(400, request=request)

        class Inner:
            async def complete(self, **kw):
                calls["n"] += 1
                raise openai.BadRequestError("bad", response=response, body=None)

        gw = OpenAICompatGateway(inner=Inner(), retry_delays=(0.0, 0.0))
        with pytest.raises(openai.BadRequestError):
            await gw.ask_json(base_url="", api_key="", model="m", messages=[],
                              purpose="speech")
        assert calls["n"] == 1, "4xx 参数错不该重试"
