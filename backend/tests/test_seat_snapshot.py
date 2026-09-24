"""座位快照测试（Red 先行，M7）：人设/接入/单价在创建时固化，历史对局可复现。

回归背景：style/strategy 曾只进内存、每次从当前 personas.json 现取，
改配置后老对局的人设无法还原（D10/D11 承诺的「创建时展开固化」没落地）。
"""

import json

import httpx
import pytest

from app.api.app import create_app

PROVIDERS = {"providers": [
    {"id": "mimo", "base_url": "https://x.example/v1", "api_key_env": "MIMO_API_KEY",
     "currency": "CNY",
     "models": [{"id": "mimo-flash", "price_per_mtok_in": 1.5,
                 "price_per_mtok_out": 6.0, "price_per_mtok_cached_in": 0.15}]},
    {"id": "mock", "base_url": "", "api_key_env": "", "currency": "CNY",
     "models": [{"id": "mock", "price_per_mtok_in": 0, "price_per_mtok_out": 0}]},
]}


def _personas(style: str) -> dict:
    return {"personas": [{"id": "direct", "name": "直球选手",
                          "style": style, "strategy": "有怀疑直说。",
                          "provider_id": "mimo", "model": "mimo-flash"}]}


def _seats() -> list[dict]:
    return [{"seat": i, "persona_id": "direct"} for i in range(1, 10)]


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("MIMO_API_KEY", "tp-secret")
    d = tmp_path / "data"
    d.mkdir()
    (d / "providers.json").write_text(json.dumps(PROVIDERS, ensure_ascii=False),
                                      encoding="utf-8")
    (d / "personas.json").write_text(json.dumps(_personas("最初的人设"), ensure_ascii=False),
                                     encoding="utf-8")
    return d


class TestSeatSnapshot:
    async def test_创建时固化人设与单价(self, tmp_path, data_dir):
        app = create_app(db_path=str(tmp_path / "s.db"), data_dir=str(data_dir))
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
                m = (await c.post("/api/matches", json={
                    "board": {"id": "p9-standard"}, "seats": _seats()})).json()
                seat = m["seats"][0]
                assert seat["style"] == "最初的人设"
                assert seat["strategy"] == "有怀疑直说。"
                assert seat["provider_id"] == "mimo"
                assert seat["model"] == "mimo-flash"
                assert seat["price_per_mtok_in"] == 1.5
                assert seat["price_per_mtok_out"] == 6.0
                assert seat["price_per_mtok_cached_in"] == 0.15
                # key 本体绝不落库
                assert "tp-secret" not in json.dumps(m, ensure_ascii=False)

                # 运行中的 runner 用的也是快照（不是现取配置）
                runner = app.state.runners[m["id"]]
                assert runner._seat_meta[1]["style"] == "最初的人设"
                assert runner._seat_meta[1]["price_per_mtok_in"] == 1.5

                # 改配置后重启一个 app（同一个库）：历史对局快照不变，新对局用新配置
                (data_dir / "personas.json").write_text(
                    json.dumps(_personas("改过的人设"), ensure_ascii=False), encoding="utf-8")
                app2 = create_app(db_path=str(tmp_path / "s.db"), data_dir=str(data_dir))
                async with app2.router.lifespan_context(app2):
                    transport2 = httpx.ASGITransport(app=app2)
                    async with httpx.AsyncClient(transport=transport2,
                                                 base_url="http://t") as c2:
                        got = (await c2.get(f"/api/matches/{m['id']}")).json()
                        assert got["seats"][0]["style"] == "最初的人设"
                        m2 = (await c2.post("/api/matches", json={
                            "board": {"id": "p9-standard"}, "seats": _seats()})).json()
                        assert m2["seats"][0]["style"] == "改过的人设"
                        await c2.post(f"/api/matches/{m2['id']}/stop")
                await c.post(f"/api/matches/{m['id']}/stop")

    async def test_默认persona绑定展开(self, tmp_path, data_dir):
        """座位不指定接入时，persona 绑定展开为 provider/model/单价。"""
        app = create_app(db_path=str(tmp_path / "s2.db"), data_dir=str(data_dir))
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
                m = (await c.post("/api/matches", json={
                    "board": {"id": "p9-standard"}, "seats": _seats()})).json()
                assert all(s["base_url"] == "https://x.example/v1" for s in m["seats"])
                assert all(s["api_key_env"] == "MIMO_API_KEY" for s in m["seats"])
                await c.post(f"/api/matches/{m['id']}/stop")
