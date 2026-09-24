"""e2e_real 座位构建测试（Red 先行）：从 providers + .env 变量构造真实座位列表。"""

import pytest

from app.scripts_helpers.e2e import build_real_seats, pick_provider

PROVIDERS = [
    {"id": "mock", "base_url": "", "api_key_env": "", "currency": "CNY",
     "models": [{"id": "mock"}]},
    {"id": "mimo", "base_url": "https://x.example/v1", "api_key_env": "MIMO_API_KEY",
     "currency": "CNY",
     "models": [{"id": "mimo-v2.6-flash", "price_per_mtok_in": 1.0,
                 "price_per_mtok_out": 3.0},
                {"id": "mimo-v2.6-pro", "price_per_mtok_in": 0,
                 "price_per_mtok_out": 0}]},
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
        seats, assignments = build_real_seats(p, model, n_players=6,
                                              env={"MIMO_API_KEY": "k"}, seed=42)
        assert len(seats) == 6
        s1 = seats[0]
        assert s1["model"] in ("mimo-v2.6-flash", "mimo-v2.6-pro")  # 池内随机
        assert s1["base_url"] == "https://x.example/v1"
        assert s1["api_key_env"] == "MIMO_API_KEY"
        assert s1["persona_id"]
        assert len(assignments) == 6

    async def test_key缺失_报错不静默(self):
        p, model = pick_provider(PROVIDERS)
        with pytest.raises(ValueError, match="MIMO_API_KEY"):
            build_real_seats(p, model, n_players=6, env={})


class TestRandomModelAssignment:
    """未绑定 persona 的座位从 provider 模型池随机分配模型（seed 可复现，分配留痕）。"""

    PERSONAS = [
        {"id": "pro", "name": "强攻手", "provider_id": "mimo", "model": "mimo-v2.6-pro"},
        {"id": "free", "name": "自由人"},  # 无绑定 → 随机分配
    ]

    def test_未绑定的随机分配_绑定的不受影响(self):
        seats, assignments = build_real_seats(
            PROVIDERS[1], "mimo-v2.6-flash", n_players=4,
            personas=self.PERSONAS, env={"MIMO_API_KEY": "k"}, seed=42)
        # 绑定的座位不变
        assert seats[0]["model"] == "mimo-v2.6-pro"
        assert seats[2]["model"] == "mimo-v2.6-pro"
        # 未绑定的座位 model 来自池子
        pool = {"mimo-v2.6-flash", "mimo-v2.6-pro"}
        assert seats[1]["model"] in pool
        assert seats[3]["model"] in pool
        # 同 seed 下未绑定座位的随机结果与分配记录一致
        for a in assignments:
            assert a["model"] == seats[a["seat"] - 1]["model"]

    def test_同seed可复现_不同seed可能不同(self):
        s1, a1 = build_real_seats(PROVIDERS[1], "mimo-v2.6-flash", n_players=4,
                                  personas=self.PERSONAS, env={"MIMO_API_KEY": "k"}, seed=7)
        s2, a2 = build_real_seats(PROVIDERS[1], "mimo-v2.6-flash", n_players=4,
                                  personas=self.PERSONAS, env={"MIMO_API_KEY": "k"}, seed=7)
        assert [s["model"] for s in s1] == [s["model"] for s in s2]
        assert a1 == a2

    def test_分配记录含persona与模型(self):
        _, assignments = build_real_seats(
            PROVIDERS[1], "mimo-v2.6-flash", n_players=2,
            personas=self.PERSONAS, env={"MIMO_API_KEY": "k"}, seed=1)
        free_entries = [a for a in assignments if a["persona_id"] == "free"]
        assert len(free_entries) == 1
        assert free_entries[0]["seat"] == 2
        assert free_entries[0]["model"] in ("mimo-v2.6-flash", "mimo-v2.6-pro")
        assert free_entries[0]["basis"] == "random"  # 区别于 persona 绑定

    def test_绑定的座位basis为persona_binding(self):
        _, assignments = build_real_seats(
            PROVIDERS[1], "mimo-v2.6-flash", n_players=1,
            personas=self.PERSONAS, env={"MIMO_API_KEY": "k"}, seed=1)
        assert assignments[0]["basis"] == "persona_binding"
        assert assignments[0]["model"] == "mimo-v2.6-pro"

    def test_不传personas_全部随机分配(self):
        seats, assignments = build_real_seats(
            PROVIDERS[1], "mimo-v2.6-flash", n_players=3, env={"MIMO_API_KEY": "k"},
            seed=5, assignment_pool=["mimo-v2.6-flash", "mimo-v2.6-pro"])
        assert all(s["model"] in ("mimo-v2.6-flash", "mimo-v2.6-pro") for s in seats)
        assert len(assignments) == 3
        assert all(a["basis"] == "random" for a in assignments)
        # 记录与座位一一对应
        for a in assignments:
            assert a["model"] == seats[a["seat"] - 1]["model"]

    def test_池子单模型_退化为全用该模型(self):
        seats, _ = build_real_seats(
            PROVIDERS[0], "mock", n_players=2, env={},
            personas=[{"id": "free", "name": "自由人"}], seed=3,
            assignment_pool=["mock"])
        assert all(s["model"] == "mock" for s in seats)

    def test_assignment_pool_for_指定model收窄池子(self):
        """CLI --model 指定时，随机池收窄为该模型（显式覆盖优先于全池随机）。"""
        from app.scripts_helpers.e2e import assignment_pool_for

        p = PROVIDERS[1]
        assert assignment_pool_for(p, "mimo-v2.6-pro") == ["mimo-v2.6-pro"]
        # 指定 --model 时收窄为单元素池（即便 provider 有多个模型）
        assert assignment_pool_for(p, "mimo-v2.6-flash") == ["mimo-v2.6-flash"]
        assert sorted(assignment_pool_for(p, "")) == ["mimo-v2.6-flash", "mimo-v2.6-pro"]
        # mock provider 无模型列表时回落
        assert assignment_pool_for(PROVIDERS[0], "") == ["mock"]
