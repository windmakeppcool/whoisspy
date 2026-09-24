"""e2e_real 座位构建测试（Red 先行）：从 providers + .env 变量构造真实座位列表。"""

import pytest

from app.scripts_helpers.e2e import build_real_seats, pick_provider

PROVIDERS = [
    {"id": "mock", "base_url": "", "api_key_env": "", "currency": "CNY",
     "models": [{"id": "mock"}]},
    {"id": "mimo", "base_url": "https://x.example/v1", "api_key_env": "MIMO_API_KEY",
     "currency": "CNY",
     "models": [{"id": "mimo-v2.6-flash", "price_per_mtok_in": 1.0,
                 "price_per_mtok_out": 3.0}]},
]


class TestPickProvider:
    async def test_默认选第一个非mock(self):
        p, model = pick_provider(PROVIDERS)
        assert p["id"] == "mimo"
        assert model == "mimo-v2.6-flash"

    async def test_全mock时返回mock(self):
        p, model = pick_provider(PROVIDERS[:1])
        assert p["id"] == "mock" and model == "mock"


class TestBuildRealSeats:
    async def test_构造6座位_带模型与变量名(self):
        p, model = pick_provider(PROVIDERS)
        seats = build_real_seats(p, model, n_players=6, env={"MIMO_API_KEY": "k"})
        assert len(seats) == 6
        s1 = seats[0]
        assert s1["model"] == "mimo-v2.6-flash"
        assert s1["base_url"] == "https://x.example/v1"
        assert s1["api_key_env"] == "MIMO_API_KEY"
        assert s1["persona_id"]

    async def test_key缺失_报错不静默(self):
        p, model = pick_provider(PROVIDERS)
        with pytest.raises(ValueError, match="MIMO_API_KEY"):
            build_real_seats(p, model, n_players=6, env={})


class TestPersonaBoundSeats:
    """e2e/TUI 支持 persona 绑定：座位按 persona 的 provider/model 构建同桌混搭（D18）。"""

    PERSONAS = [
        {"id": "pro", "name": "强攻手", "provider_id": "mimo", "model": "mimo-v2.6-pro"},
        {"id": "flash", "name": "快枪手", "provider_id": "mimo", "model": "mimo-v2.6-flash"},
        {"id": "free", "name": "自由人"},  # 无绑定 → 用默认 provider/model
    ]

    def test_按persona绑定分配座位(self):
        seats = build_real_seats(
            PROVIDERS[1], "mimo-v2.6-flash", n_players=4,
            personas=self.PERSONAS, env={"MIMO_API_KEY": "k"})
        assert len(seats) == 4
        # persona 循环取用：pro, flash, free, pro
        assert seats[0]["model"] == "mimo-v2.6-pro"
        assert seats[1]["model"] == "mimo-v2.6-flash"
        assert seats[2]["model"] == "mimo-v2.6-flash"  # free → 默认
        assert seats[3]["model"] == "mimo-v2.6-pro"
        assert all(s["base_url"] == "https://x.example/v1" for s in seats)
        assert all(s["api_key_env"] == "MIMO_API_KEY" for s in seats)

    def test_persona绑定的key变量缺失_报错(self):
        with pytest.raises(ValueError, match="MIMO_API_KEY"):
            build_real_seats(PROVIDERS[1], "mimo-v2.6-flash", n_players=2,
                             personas=self.PERSONAS, env={})

    def test_不传personas_保持原行为(self):
        seats = build_real_seats(PROVIDERS[1], "mimo-v2.6-flash", n_players=3,
                                 env={"MIMO_API_KEY": "k"})
        assert all(s["model"] == "mimo-v2.6-flash" for s in seats)
