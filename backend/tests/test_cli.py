"""config 与 CLI 测试（Red 先行）：docs/backend/09-config.md + 12-cli.md。"""

import json

import pytest

from app.config import build_seats, load_env_file, load_personas, load_providers


# ---------- 配置加载 ----------

def _providers_json():
    return {"providers": [
        {"id": "demo", "base_url": "https://api.demo/v1", "api_key_env": "DEMO_KEY",
         "models": [{"id": "m-a", "price_per_mtok_in": 2.0, "price_per_mtok_out": 8.0,
                     "price_per_mtok_cached_in": 0.5},
                    {"id": "m-b"}]},
        {"id": "mock", "base_url": "", "api_key_env": "",
         "models": [{"id": "mock"}]},
    ]}


def _personas_json():
    return {"personas": [
        {"id": "aggressive", "name": "悍跳", "style": "强硬", "strategy": "悍跳",
         "provider_id": "demo", "model": "m-a"},
        {"id": "calm", "name": "冷静", "style": "克制", "strategy": "盘逻辑"},
    ]}


def test_加载providers校验(tmp_path):
    f = tmp_path / "providers.json"
    f.write_text(json.dumps(_providers_json()), encoding="utf-8")
    data = load_providers(str(f))
    assert data.providers[0].models[0].price_per_mtok_cached_in == 0.5
    assert data.providers[0].models[1].price_per_mtok_in == 0.0  # 缺省 0


def test_加载personas校验(tmp_path):
    f = tmp_path / "personas.json"
    f.write_text(json.dumps(_personas_json()), encoding="utf-8")
    data = load_personas(str(f))
    assert data.personas[0].model == "m-a"


def test_坏配置拒绝加载(tmp_path):
    f = tmp_path / "p.json"
    f.write_text('{"providers": "not-a-list"}', encoding="utf-8")
    with pytest.raises(ValueError):
        load_providers(str(f))


def test_env文件加载(tmp_path):
    f = tmp_path / ".env"
    f.write_text("A=1\n# 注释\nB=\"quoted\"\n", encoding="utf-8")
    env = {"A": "existing"}
    load_env_file(str(f), env=env)
    assert env["A"] == "existing"  # 已有环境变量优先
    assert env["B"] == "quoted"


# ---------- 座位接入构建 ----------

def test_座位构建persona绑定优先():
    providers = load_providers.__wrapped__ if hasattr(load_providers, "__wrapped__") else None
    from app.config import _providers_from_dict, _personas_from_dict

    seats, assignments = build_seats(
        n_players=4, personas=_personas_from_dict(_personas_json()),
        providers=_providers_from_dict(_providers_json()),
        env={"DEMO_KEY": "k"}, seed=42)
    # 座位 1、3 是 aggressive（绑定 m-a）；2、4 是 calm（池内随机）
    assert seats[0]["model"] == "m-a"
    assert assignments[0]["basis"] == "persona_binding"
    assert seats[0]["base_url"] == "https://api.demo/v1"
    assert seats[0]["api_key_env"] == "DEMO_KEY"
    assert seats[1]["model"] in ("m-a", "m-b")  # 池内随机
    assert assignments[1]["basis"] == "random"
    assert seats[0]["price_per_mtok_in"] == 2.0


def test_座位构建同seed复现():
    from app.config import _personas_from_dict, _providers_from_dict

    a = build_seats(n_players=4, personas=_personas_from_dict(_personas_json()),
                    providers=_providers_from_dict(_providers_json()),
                    env={"DEMO_KEY": "k"}, seed=7)
    b = build_seats(n_players=4, personas=_personas_from_dict(_personas_json()),
                    providers=_providers_from_dict(_providers_json()),
                    env={"DEMO_KEY": "k"}, seed=7)
    assert a[0] == b[0] and a[1] == b[1]


def test_座位构建model收窄池():
    from app.config import _personas_from_dict, _providers_from_dict

    seats, assignments = build_seats(
        n_players=4, personas=_personas_from_dict(_personas_json()),
        providers=_providers_from_dict(_providers_json()),
        env={"DEMO_KEY": "k"}, seed=42, model="m-b")
    # 绑定优先：aggressive（1、3 号）仍 m-a；随机座位（2、4 号）池被收窄为 m-b
    assert seats[0]["model"] == "m-a"
    assert seats[1]["model"] == "m-b"
    assert seats[2]["model"] == "m-a"
    assert seats[3]["model"] == "m-b"


def test_座位构建缺key报错():
    from app.config import _personas_from_dict, _providers_from_dict

    with pytest.raises(ValueError, match="DEMO_KEY"):
        build_seats(n_players=2, personas=_personas_from_dict(_personas_json()),
                    providers=_providers_from_dict(_providers_json()),
                    env={}, seed=42)


def test_座位构建persona绑定不存在的provider报错():
    from app.config import _personas_from_dict, _providers_from_dict

    ps = _personas_json()
    ps["personas"][0]["provider_id"] = "ghost"
    with pytest.raises(ValueError, match="ghost"):
        build_seats(n_players=2, personas=_personas_from_dict(ps),
                    providers=_providers_from_dict(_providers_json()),
                    env={"DEMO_KEY": "k"}, seed=42)


# ---------- CLI 冒烟 ----------

async def test_cli_mock跑完整局(tmp_path):
    from app.main import main

    out = tmp_path / "export.json"
    code = await main(["--mock", "--seed", "42", "--out", str(out),
                       "--db", str(tmp_path / "t.db")])
    assert code == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["match"]["status"] == "finished"
    assert doc["match"]["winner"] in ("wolf", "good")
    assert doc["usage"]["calls"] > 0
    labels = [s["label"] for s in doc["segments"]]
    assert labels[0] == "开局"
    assert "第一夜" in labels


async def test_cli_调用超限退出码2(tmp_path):
    from app.main import main

    code = await main(["--mock", "--seed", "42", "--max-calls", "10",
                       "--db", str(tmp_path / "t.db"),
                       "--out", str(tmp_path / "x.json")])
    assert code == 2  # stopped


async def test_cli_real无key退出码3(tmp_path):
    from app.main import main

    # real 模式：默认 data/ 下没有 providers.json → 配置错误
    code = await main(["--real", "--db", str(tmp_path / "t.db"),
                       "--out", str(tmp_path / "x.json")])
    assert code == 3


async def test_cli_参数解析():
    from app.main import parse_args

    args = parse_args(["--mock", "--seed", "1", "--out", "o.json",
                       "--view", "public", "--trace", "tr", "--max-days", "5",
                       "--wolf-rounds", "1", "--max-calls", "50"])
    assert args.seed == 1
    assert args.view == "public"
    assert args.max_days == 5
    assert args.wolf_rounds == 1
    assert args.max_calls == 50
    assert args.trace == "tr"
    args2 = parse_args([])
    assert args2.mock is True and args2.seed is None
    assert args2.max_days == 8 and args2.wolf_rounds == 2 and args2.max_calls == 600