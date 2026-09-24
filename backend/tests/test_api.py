"""API 层测试（Red 先行）：创建对局/列表/详情/事件回填/用量/可见性/stop。"""

import asyncio

import httpx
import pytest

from app.api.app import create_app
from app.storage.repo import SqliteMatchRepository


@pytest.fixture()
async def client(tmp_path):
    app = create_app(db_path=str(tmp_path / "api.db"))
    # httpx ASGITransport 不触发 lifespan，手动进入以初始化建表
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            yield c


SEATS = [{"seat": i, "persona_id": "calm-analyst", "base_url": "", "api_key_env": "",
          "model": "mock", "name": f"p{i}"} for i in range(1, 10)]


async def _create(client: httpx.AsyncClient, **overrides) -> dict:
    body = {"game_type": "werewolf", "board": {"id": "p9-standard"}, "seats": SEATS}
    body.update(overrides)
    resp = await client.post("/api/matches", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestMatchApi:
    async def test_创建对局返回配置(self, client):
        m = await _create(client)
        assert m["id"] > 0 and m["status"] in ("created", "running", "finished")
        assert len(m["seats"]) == 9
        assert m["ruleset"] == "standard-9"

    async def test_坏板子422(self, client):
        resp = await client.post("/api/matches", json={
            "game_type": "werewolf",
            "board": {"ruleset": "minimal", "roles": {"wolf": 2, "villager": 4}},
            "seats": SEATS})
        assert resp.status_code == 422

    async def test_未知板子id_422(self, client):
        resp = await client.post("/api/matches", json={
            "game_type": "werewolf", "board": {"id": "p6-classic"}, "seats": SEATS})
        assert resp.status_code == 422
        assert "未知板子" in resp.text

    async def test_列表与详情(self, client):
        m = await _create(client)
        rows = (await client.get("/api/matches")).json()
        assert any(r["id"] == m["id"] for r in rows)
        got = (await client.get(f"/api/matches/{m['id']}")).json()
        assert got["board"]["roles"]["wolf"] == 3

    async def test_详情404(self, client):
        resp = await client.get("/api/matches/99999")
        assert resp.status_code == 404

    async def test_事件回填_view过滤(self, client):
        m = await _create(client)
        await asyncio.sleep(0.3)  # 让 runner 跑一点
        god = (await client.get(f"/api/matches/{m['id']}/events",
                                params={"after_seq": 0, "view": "god"})).json()
        imm = (await client.get(f"/api/matches/{m['id']}/events",
                                params={"after_seq": 0, "view": "immersive"})).json()
        assert god and all(ev["seq"] > 0 for ev in god)
        forbidden = {"channel.message", "player.monologue", "player.fallback",
                     "night.kill_target", "role.dealt"}
        assert not any(ev["type"] in forbidden for ev in imm)

    async def test_事件after_seq增量(self, client):
        m = await _create(client)
        await asyncio.sleep(0.3)
        first = (await client.get(f"/api/matches/{m['id']}/events",
                                  params={"after_seq": 0, "view": "god"})).json()
        if len(first) >= 2:
            cut = first[0]["seq"]
            rest = (await client.get(f"/api/matches/{m['id']}/events",
                                     params={"after_seq": cut, "view": "god"})).json()
            assert all(ev["seq"] > cut for ev in rest)

    async def test_事件出站携带vis字段(self, client):
        """出站事件需带 vis——TUI 客户端沉浸过滤的依据。"""
        m = await _create(client)
        await asyncio.sleep(0.3)
        god = (await client.get(f"/api/matches/{m['id']}/events",
                                params={"after_seq": 0, "view": "god"})).json()
        assert god
        for ev in god:
            assert "vis" in ev, f"事件 {ev['type']} 缺 vis 字段"
            assert ev["vis"]["level"] in ("public", "seat", "god")
        dealt = [ev for ev in god if ev["type"] == "role.dealt"]
        if dealt:
            assert dealt[0]["vis"]["level"] == "seat"

    async def test_用量端点(self, client):
        m = await _create(client)
        resp = await client.get(f"/api/matches/{m['id']}/usage")
        assert resp.status_code == 200
        body = resp.json()
        assert "total_calls" in body and "cost_micros" in body

    async def test_牌桌与档案目录(self, client):
        boards = (await client.get("/api/catalog/boards")).json()
        # 单板收敛：目录里只有 p9-standard（D23）
        assert [b["id"] for b in boards] == ["p9-standard"]
        personas = (await client.get("/api/catalog/personas")).json()
        assert personas and "style" in personas[0]

    async def test_stop端点(self, client):
        m = await _create(client)
        resp = await client.post(f"/api/matches/{m['id']}/stop")
        assert resp.status_code == 200
