"""API 输入校验 / 契约 / 安全测试（Red 先行）：

- M8：座位号必须恰好是 1..N 且不重复；未知 persona 必须 422（不得静默回落）
- M9：provider_ref 引用 providers.json 预设（api.md 契约）；Last-Event-ID 头可续传
- M10：lifespan 退出时在跑的对局必须被中断并落 stopped，不留悬挂 task
- M11：base_url/api_key_env 必须来自 providers.json（防把真实 key 发到任意地址）；
       CORS 收敛到允许来源；可选 API token
"""

import asyncio
import json
import os

import httpx
import pytest

from app.api.app import create_app

PERSONAS = {"personas": [{"id": "direct", "name": "直球选手",
                          "style": "简短直接。", "strategy": "有怀疑直说。"}]}
PROVIDERS = {"providers": [
    {"id": "mimo", "base_url": "https://x.example/v1", "api_key_env": "MIMO_API_KEY",
     "currency": "CNY", "models": [{"id": "mimo-flash", "price_per_mtok_in": 1.0,
                                    "price_per_mtok_out": 2.0}]},
    {"id": "mock", "base_url": "", "api_key_env": "", "currency": "CNY",
     "models": [{"id": "mock", "price_per_mtok_in": 0.0, "price_per_mtok_out": 0.0}]},
]}


def _write_cfg(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    (d / "personas.json").write_text(json.dumps(PERSONAS, ensure_ascii=False),
                                     encoding="utf-8")
    (d / "providers.json").write_text(json.dumps(PROVIDERS, ensure_ascii=False),
                                      encoding="utf-8")
    return d


def _seats(nums=(1, 2, 3, 4, 5, 6, 7, 8, 9), **kw) -> list[dict]:
    return [{"seat": i, "persona_id": kw.get("persona_id", "direct"),
             "model": kw.get("model", "mock"), "name": f"p{i}"} for i in nums]


def _body(seats=None, board=None) -> dict:
    return {"game_type": "werewolf", "board": board or {"id": "p9-standard"},
            "seats": seats if seats is not None else _seats()}


@pytest.fixture()
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MIMO_API_KEY", "tp-secret")
    d = _write_cfg(tmp_path)
    app = create_app(db_path=str(tmp_path / "api.db"), data_dir=str(d))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            yield c


class TestSeatValidation:
    @pytest.mark.parametrize("nums", [
        (1, 2, 3, 4, 5, 6, 7, 8, 8),          # 重复
        (0, 1, 2, 3, 4, 5, 6, 7, 8),          # 越界（有 0 无 9）
        (-1, 1, 2, 3, 4, 5, 6, 7, 8),         # 负数
        (1, 2, 3, 4, 5, 6, 7, 8, 99),         # 越界
        (2, 3, 4, 5, 6, 7, 8, 9, 10),         # 错位（不是 1..9）
    ])
    async def test_座位号非法_422(self, client, nums):
        resp = await client.post("/api/matches", json=_body(_seats(nums)))
        assert resp.status_code == 422, resp.text

    async def test_座位数不符_422(self, client):
        resp = await client.post("/api/matches", json=_body(_seats((1, 2, 3))))
        assert resp.status_code == 422

    async def test_未知persona_422(self, client):
        resp = await client.post("/api/matches",
                                 json=_body(_seats(persona_id="no-such-persona")))
        assert resp.status_code == 422
        assert "persona" in resp.text or "选手" in resp.text

    async def test_合法座位_200(self, client):
        resp = await client.post("/api/matches", json=_body())
        assert resp.status_code == 200, resp.text
        m = resp.json()
        assert [s["seat"] for s in m["seats"]] == list(range(1, 10))
        assert all(s["role"] == "" for s in m["seats"])
        # 每个座位一条记录，绝无重复座位
        assert len({s["seat"] for s in m["seats"]}) == 9


class TestProviderRef:
    """api.md：provider_ref 引用 providers.json 预设并展开固化。"""

    async def test_provider_ref展开预设(self, client):
        seats = [{"seat": i, "persona_id": "direct",
                  "provider_ref": "mimo/mimo-flash"} for i in range(1, 10)]
        resp = await client.post("/api/matches", json=_body(seats))
        assert resp.status_code == 200, resp.text
        for s in resp.json()["seats"]:
            assert s["model"] == "mimo-flash"
            assert s["base_url"] == "https://x.example/v1"
            assert s["api_key_env"] == "MIMO_API_KEY"

    async def test_provider_ref只用provider取首模型(self, client):
        seats = [{"seat": i, "persona_id": "direct", "provider_ref": "mimo"}
                 for i in range(1, 10)]
        resp = await client.post("/api/matches", json=_body(seats))
        assert resp.status_code == 200, resp.text
        assert all(s["model"] == "mimo-flash" for s in resp.json()["seats"])

    async def test_provider_ref未知_422(self, client):
        seats = [{"seat": i, "persona_id": "direct", "provider_ref": "nope/model-x"}
                 for i in range(1, 10)]
        resp = await client.post("/api/matches", json=_body(seats))
        assert resp.status_code == 422

    async def test_provider_ref模型不属于该provider_422(self, client):
        seats = [{"seat": i, "persona_id": "direct", "provider_ref": "mimo/nope"}
                 for i in range(1, 10)]
        resp = await client.post("/api/matches", json=_body(seats))
        assert resp.status_code == 422


class TestSecurity:
    """M11：座位接入必须来自 providers.json，不得把真实 key 发到任意地址。"""

    async def test_裸base_url不在配置内_422(self, client):
        seats = [{"seat": i, "persona_id": "direct", "model": "mimo-flash",
                  "base_url": "https://evil.example/v1", "api_key_env": "MIMO_API_KEY"}
                 for i in range(1, 10)]
        resp = await client.post("/api/matches", json=_body(seats))
        assert resp.status_code == 422, resp.text
        assert "base_url" in resp.text or "providers" in resp.text

    async def test_配置内base_url_允许(self, client):
        seats = [{"seat": i, "persona_id": "direct", "model": "mimo-flash",
                  "base_url": "https://x.example/v1", "api_key_env": "MIMO_API_KEY"}
                 for i in range(1, 10)]
        resp = await client.post("/api/matches", json=_body(seats))
        assert resp.status_code == 200, resp.text

    async def test_key环境变量缺失_422(self, client, monkeypatch):
        monkeypatch.delenv("MIMO_API_KEY", raising=False)
        seats = [{"seat": i, "persona_id": "direct", "provider_ref": "mimo/mimo-flash"}
                 for i in range(1, 10)]
        resp = await client.post("/api/matches", json=_body(seats))
        assert resp.status_code == 422
        assert "MIMO_API_KEY" in resp.text

    async def test_cors只放行白名单来源(self, client):
        ok = await client.options("/api/matches", headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST"})
        assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
        bad = await client.options("/api/matches", headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST"})
        assert bad.headers.get("access-control-allow-origin") != "https://evil.example"

    async def test_可选token开启后必须携带(self, tmp_path, monkeypatch):
        monkeypatch.setenv("WHOISSPY_API_TOKEN", "s3cret")
        d = _write_cfg(tmp_path)
        app = create_app(db_path=str(tmp_path / "tok.db"), data_dir=str(d))
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
                r1 = await c.get("/api/matches")
                assert r1.status_code == 401
                r2 = await c.get("/api/matches",
                                 headers={"X-API-Token": "s3cret"})
                assert r2.status_code == 200
                r3 = await c.get("/api/matches",
                                 headers={"Authorization": "Bearer s3cret"})
                assert r3.status_code == 200
                r4 = await c.get("/api/matches", headers={"X-API-Token": "wrong"})
                assert r4.status_code == 401
        monkeypatch.delenv("WHOISSPY_API_TOKEN", raising=False)

    async def test_未开token时无需鉴权(self, client):
        assert (await client.get("/api/matches")).status_code == 200


class TestHttpContract:
    async def test_未知对局stop_404(self, client):
        assert (await client.post("/api/matches/9999/stop")).status_code == 404

    async def test_未知对局usage_404(self, client):
        assert (await client.get("/api/matches/9999/usage")).status_code == 404

    async def test_创建事件落库(self, client):
        """api.md：校验通过即落 match.created。"""
        m = (await client.post("/api/matches", json=_body())).json()
        await asyncio.sleep(0.2)
        events = (await client.get(f"/api/matches/{m['id']}/events",
                                   params={"view": "god"})).json()
        assert events[0]["type"] == "match.created"
        assert events[0]["payload"]["board_id"] == "p9-standard"

    async def test_last_event_id头可续传(self, client):
        m = (await client.post("/api/matches", json=_body())).json()
        await asyncio.sleep(0.3)
        all_ev = (await client.get(f"/api/matches/{m['id']}/events",
                                   params={"view": "god"})).json()
        cut = all_ev[0]["seq"]
        resumed = (await client.get(f"/api/matches/{m['id']}/events",
                                    headers={"Last-Event-ID": str(cut)},
                                    params={"view": "god"})).json()
        assert all(e["seq"] > cut for e in resumed)


class TestLifecycle:
    async def test_空闲关停也要关闭仓储(self, tmp_path, monkeypatch):
        """回归：没有在跑对局时，关停流程也必须 close 两个 repository（否则引擎泄漏）。"""
        from app.storage import repo as repo_mod

        calls = {"match": 0, "usage": 0}
        orig_match_close = repo_mod.SqliteMatchRepository.close
        orig_usage_close = repo_mod.SqliteUsageRepository.close

        async def spy_match_close(self):
            calls["match"] += 1
            await orig_match_close(self)

        async def spy_usage_close(self):
            calls["usage"] += 1
            await orig_usage_close(self)

        monkeypatch.setattr(repo_mod.SqliteMatchRepository, "close", spy_match_close)
        monkeypatch.setattr(repo_mod.SqliteUsageRepository, "close", spy_usage_close)

        d = _write_cfg(tmp_path)
        app = create_app(db_path=str(tmp_path / "idle.db"), data_dir=str(d))
        async with app.router.lifespan_context(app):
            pass  # 一局都不创建
        assert calls == {"match": 1, "usage": 1}

    async def test_shutdown中断在跑对局并落stopped(self, tmp_path):
        d = _write_cfg(tmp_path)
        app = create_app(db_path=str(tmp_path / "life.db"), data_dir=str(d))
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
                m = (await c.post("/api/matches",
                                  json=_body(_seats(model="mock")))).json()
            # 仍在跑（mock 局 8 天）
            assert app.state.runners
        # lifespan 退出后：不得留下悬挂 task，对局状态必须收尾
        runners = app.state.runners
        assert not runners, "关闭时应清空在跑对局注册表"

    async def test_运行中注册表可查(self, client):
        m = (await client.post("/api/matches", json=_body())).json()
        assert m["id"] in client._transport.app.state.runners
        await client.post(f"/api/matches/{m['id']}/stop")
