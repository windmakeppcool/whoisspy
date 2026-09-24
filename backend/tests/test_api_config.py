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


class TestPersonaExpansion:
    """座位未显式指定接入时，从其 persona 的 provider/model 绑定展开（D18）。"""

    async def test_persona绑定provider_座位未指定model_自动展开(self, client):
        # personas.json 里 direct 未绑定（默认文件），需要自定义 data_dir —— 此 fixture 的
        # personas 只有 direct，先给它绑 provider 覆盖场景放到独立 fixture；这里验证
        # 绑定了 provider 的 persona 被座位引用后座位 model/base_url/api_key_env 被展开
        seats = [{"seat": i, "persona_id": "direct", "name": f"p{i}"}
                 for i in range(1, 7)]
        # direct 未绑定 → 座位无 model 字段时默认 mock，行为不变
        resp = await client.post("/api/matches", json={
            "game_type": "werewolf", "board": {"id": "p6-classic"}, "seats": seats})
        assert resp.status_code == 200, resp.text
        mid = resp.json()["id"]
        m = (await client.get(f"/api/matches/{mid}")).json()
        assert all(s["model"] == "mock" for s in m["seats"])

    async def test_persona绑定后座位展开provider信息(self, tmp_path, monkeypatch):
        import json as _json

        data_dir = tmp_path / "d2"
        data_dir.mkdir()
        (data_dir / "providers.json").write_text(_json.dumps({
            "providers": [
                {"id": "mimo", "base_url": "https://x.example/v1",
                 "api_key_env": "MIMO_API_KEY", "currency": "CNY",
                 "models": [{"id": "mimo-v2.6-flash"}, {"id": "mimo-v2.6-pro"}]},
            ]}), encoding="utf-8")
        (data_dir / "personas.json").write_text(_json.dumps({
            "personas": [
                {"id": "pro-player", "name": "强攻手", "style": "s", "strategy": "t",
                 "provider_id": "mimo", "model": "mimo-v2.6-pro"},
                {"id": "flash-player", "name": "快枪手", "style": "s", "strategy": "t",
                 "provider_id": "mimo", "model": "mimo-v2.6-flash"},
            ]}, ensure_ascii=False), encoding="utf-8")
        app = create_app(db_path=str(tmp_path / "d2.db"), data_dir=str(data_dir))
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport,
                                         base_url="http://t") as c:
                seats = [{"seat": i, "persona_id": "pro-player" if i <= 3 else "flash-player",
                          "name": f"p{i}"}
                         for i in range(1, 7)]
                resp = await c.post("/api/matches", json={
                    "game_type": "werewolf", "board": {"id": "p6-classic"},
                    "seats": seats})
                assert resp.status_code == 200, resp.text
                mid = resp.json()["id"]
                m = (await c.get(f"/api/matches/{mid}")).json()
                for s in m["seats"]:
                    if s["seat"] <= 3:
                        assert s["model"] == "mimo-v2.6-pro"
                    else:
                        assert s["model"] == "mimo-v2.6-flash"
                    assert s["base_url"] == "https://x.example/v1"
                    assert s["api_key_env"] == "MIMO_API_KEY"

    async def test_座位显式指定model_优先于persona绑定(self, tmp_path):
        import json as _json

        data_dir = tmp_path / "d3"
        data_dir.mkdir()
        (data_dir / "providers.json").write_text(_json.dumps({
            "providers": [{"id": "mimo", "base_url": "https://x.example/v1",
                           "api_key_env": "MIMO_API_KEY", "currency": "CNY",
                           "models": [{"id": "mimo-v2.6-flash"}]}]}), encoding="utf-8")
        (data_dir / "personas.json").write_text(_json.dumps({
            "personas": [{"id": "pp", "name": "N", "style": "s", "strategy": "t",
                          "provider_id": "mimo", "model": "mimo-v2.6-flash"}]}),
            encoding="utf-8")
        app = create_app(db_path=str(tmp_path / "d3.db"), data_dir=str(data_dir))
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport,
                                         base_url="http://t") as c:
                seats = [{"seat": i, "persona_id": "pp", "model": "mock", "name": f"p{i}"}
                         for i in range(1, 7)]
                resp = await c.post("/api/matches", json={
                    "game_type": "werewolf", "board": {"id": "p6-classic"},
                    "seats": seats})
                assert resp.status_code == 200, resp.text
                mid = resp.json()["id"]
                m = (await c.get(f"/api/matches/{mid}")).json()
                assert all(s["model"] == "mock" for s in m["seats"])

    async def test_board的model_assignments落库透传(self, client):
        """客户端（TUI --real 等）传入的分配记录随 board 落库，复盘可查（D19 留痕）。"""
        assignments = [
            {"seat": 1, "persona_id": "direct", "model": "mimo-v2.6-pro",
             "basis": "persona_binding", "provider_id": "mimo"},
            {"seat": 2, "persona_id": "calm-analyst", "model": "mimo-v2.6-flash",
             "basis": "random", "provider_id": "mimo"},
        ]
        seats = [{"seat": i, "persona_id": "direct", "model": "mock",
                  "name": f"p{i}"} for i in range(1, 7)]
        resp = await client.post("/api/matches", json={
            "game_type": "werewolf",
            "board": {"id": "p6-classic", "model_assignments": assignments},
            "seats": seats})
        assert resp.status_code == 200, resp.text
        mid = resp.json()["id"]
        m = (await client.get(f"/api/matches/{mid}")).json()
        assert m["board"]["model_assignments"] == assignments
