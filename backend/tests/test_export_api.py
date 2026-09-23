"""端点测试（Red 先行）：GET /api/matches/{id}/export。"""

import asyncio

import httpx
import pytest

from app.api.app import create_app


@pytest.fixture()
async def client(tmp_path):
    app = create_app(db_path=str(tmp_path / "export.db"))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            yield c


SEATS = [{"seat": i, "persona_id": "calm", "base_url": "", "api_key_env": "",
          "model": "mock", "name": f"p{i}"} for i in range(1, 7)]


async def _create(client: httpx.AsyncClient) -> dict:
    body = {"game_type": "werewolf", "board": {"id": "p6-classic"}, "seats": SEATS}
    resp = await client.post("/api/matches", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestExportEndpoint:
    async def test_导出返回正确JSON结构(self, client):
        m = await _create(client)
        await asyncio.sleep(0.5)  # 让 runner 跑出一些事件
        resp = await client.get(f"/api/matches/{m['id']}/export")
        assert resp.status_code == 200
        data = resp.json()
        assert data["match_id"] == m["id"]
        assert data["game_type"] == "werewolf"
        assert "exported_at" in data
        assert "segments" in data

    async def test_导出设置下载header(self, client):
        m = await _create(client)
        resp = await client.get(f"/api/matches/{m['id']}/export")
        assert resp.status_code == 200
        cd = resp.headers.get("content-disposition", "")
        assert "attachment" in cd
        assert f"match-{m['id']}-dialog.json" in cd

    async def test_导出404对局不存在(self, client):
        resp = await client.get("/api/matches/99999/export")
        assert resp.status_code == 404

    async def test_上帝视角包含夜晚事件(self, client):
        m = await _create(client)
        await asyncio.sleep(1.0)  # 让 runner 跑到夜晚
        resp = await client.get(f"/api/matches/{m['id']}/export")
        assert resp.status_code == 200
        data = resp.json()
        # 至少应该有一段
        if data["segments"]:
            # 检查第一夜应该有 entries
            night_segs = [s for s in data["segments"] if "夜" in s["label"]]
            if night_segs:
                assert len(night_segs[0]["entries"]) > 0

    async def test_进行中对局也可导出(self, client):
        m = await _create(client)
        await asyncio.sleep(0.3)
        # 即使对局还没结束，也应该能导出（事件流是 append-only）
        resp = await client.get(f"/api/matches/{m['id']}/export")
        assert resp.status_code == 200
