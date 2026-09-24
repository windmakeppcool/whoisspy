"""API 层配置接线测试（Red 先行）：

- create_app 启动时从 data_dir 加载 JSON 配置（catalog 反映配置内容）
- _spawn_runner 解析 api_key_env → 内存 seat_meta 有真实 key
- 落库的 seat 只含变量名，不含 key 本体
"""

import json

import httpx
import pytest

from app.api.app import create_app


@pytest.fixture()
async def client(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "personas.json").write_text(json.dumps({
        "personas": [{"id": "direct", "name": "直球选手",
                      "style": "简短直接。", "strategy": "有怀疑直说。"}]
    }, ensure_ascii=False), encoding="utf-8")
    (data_dir / "providers.json").write_text(json.dumps({
        "providers": [{"id": "mimo", "base_url": "https://x.example/v1",
                       "api_key_env": "MIMO_API_KEY", "currency": "CNY",
                       "models": [{"id": "mimo-flash"}]},
                      {"id": "mock", "base_url": "", "api_key_env": "",
                       "models": [{"id": "mock"}]}]
    }), encoding="utf-8")
    monkeypatch.setenv("MIMO_API_KEY", "tp-injected")
    app = create_app(db_path=str(tmp_path / "api.db"), data_dir=str(data_dir))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            yield c


class TestConfigWiring:
    async def test_catalog来自json配置(self, client):
        personas = (await client.get("/api/catalog/personas")).json()
        assert [p["id"] for p in personas] == ["direct"]
        providers = (await client.get("/api/catalog/providers")).json()
        ids = [p["id"] for p in providers]
        assert "mimo" in ids and "mock" in ids
        # 脱敏：不返回 api_key_env
        mimo = next(p for p in providers if p["id"] == "mimo")
        assert "api_key_env" not in mimo

    async def test_真实座位_key解析进内存_不落库(self, client, tmp_path):
        seats = [{"seat": i, "persona_id": "direct", "model": "mimo-flash",
                  "base_url": "https://x.example/v1", "api_key_env": "MIMO_API_KEY",
                  "name": f"p{i}"} for i in range(1, 7)]
        resp = await client.post("/api/matches", json={
            "game_type": "werewolf", "board": {"id": "p6-classic"}, "seats": seats})
        assert resp.status_code == 200, resp.text
        mid = resp.json()["id"]
        m = (await client.get(f"/api/matches/{mid}")).json()
        # 落库 seat 只有变量名，绝无 key 本体
        for s in m["seats"]:
            assert s["api_key_env"] == "MIMO_API_KEY"
            assert "tp-injected" not in json.dumps(m, ensure_ascii=False)
        # runner 的 seat_meta（内存）已解析出真实 key
        runner = next(r for r in _runners_of(client) if r._mid == mid)
        meta = runner._seat_meta[1]
        assert meta["api_key"] == "tp-injected"
        assert meta["api_key_env"] == "MIMO_API_KEY"


def _runners_of(client: httpx.AsyncClient) -> list:
    app = client._transport.app  # ASGITransport 持有 app
    return list(app.state.runners.values())
