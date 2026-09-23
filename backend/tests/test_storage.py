"""存储层测试（Red 先行）：seq 分配、append-only、可见性过滤、用量记录与汇总。"""

import pytest

from app.core import Event, VisMeta
from app.storage.repo import MatchRepository, UsageRepository, SqliteMatchRepository, SqliteUsageRepository


@pytest.fixture()
async def repo(tmp_path):
    r = SqliteMatchRepository(db_path=str(tmp_path / "t.db"))
    await r.init()
    yield r
    await r.close()


@pytest.fixture()
async def usage_repo(tmp_path):
    r = SqliteUsageRepository(db_path=str(tmp_path / "t.db"))
    await r.init()
    yield r
    await r.close()


SEATS = [{"seat": 1, "name": "甲", "persona_id": "p1", "base_url": "https://x/v1",
          "api_key_env": "K1", "model": "m1", "role": "wolf"}]


async def _make_match(repo: MatchRepository, seats=None):
    return await repo.create_match(
        game_type="werewolf", ruleset="minimal",
        board={"roles": {"wolf": 2, "seer": 1, "villager": 3}},
        rng_seed=42, seats=seats or SEATS,
    )


class TestMatchRepo:
    async def test_创建对局返回id与配置(self, repo):
        m = await _make_match(repo)
        assert m["id"] > 0
        assert m["status"] == "created"
        assert m["rng_seed"] == 42
        got = await repo.get_match(m["id"])
        assert got is not None
        assert got["board"]["roles"]["wolf"] == 2
        assert got["seats"][0]["model"] == "m1"
        assert got["seats"][0]["role"] == "wolf"

    async def test_事件seq从1单调递增(self, repo):
        m = await _make_match(repo)
        s1 = await repo.append_event(m["id"], Event(type="match.started", payload={}))
        s2 = await repo.append_event(m["id"], Event(type="phase.started", payload={}))
        assert (s1.seq, s2.seq) == (1, 2)

    async def test_列出事件按seq且支持after_seq(self, repo):
        m = await _make_match(repo)
        for i in range(5):
            await repo.append_event(m["id"], Event(type="t", payload={"i": i}))
        all_events = await repo.list_events(m["id"], after_seq=0, view="god")
        assert [e.seq for e in all_events] == [1, 2, 3, 4, 5]
        later = await repo.list_events(m["id"], after_seq=3, view="god")
        assert [e.seq for e in later] == [4, 5]

    async def test_视角过滤immersive只留public(self, repo):
        m = await _make_match(repo)
        await repo.append_event(m["id"], Event(type="a", payload={}, vis=VisMeta(level="public")))
        await repo.append_event(m["id"], Event(type="b", payload={}, vis=VisMeta(level="god")))
        await repo.append_event(m["id"], Event(type="c", payload={}, vis=VisMeta(level="seat", seats=[1])))
        immersive = await repo.list_events(m["id"], after_seq=0, view="immersive")
        assert [e.type for e in immersive] == ["a"]

    async def test_更新对局状态与结果(self, repo):
        m = await _make_match(repo)
        await repo.update_match(m["id"], status="running")
        await repo.update_match(m["id"], status="finished",
                                result={"winner": "wolf", "reason": "x"})
        got = await repo.get_match(m["id"])
        assert got["status"] == "finished"
        assert got["result"]["winner"] == "wolf"

    async def test_角色回填座位表(self, repo):
        seats = [
            {"seat": 1, "name": "甲", "persona_id": "p1", "base_url": "https://x/v1",
             "api_key_env": "K1", "model": "m1", "role": ""},
            {"seat": 2, "name": "乙", "persona_id": "p2", "base_url": "https://x/v1",
             "api_key_env": "K2", "model": "m2", "role": ""},
        ]
        m = await _make_match(repo, seats=seats)
        await repo.set_seat_roles(m["id"], {1: "wolf", 2: "seer"})
        got = await repo.get_match(m["id"])
        assert got["seats"][0]["role"] == "wolf"
        assert got["seats"][1]["role"] == "seer"

    async def test_列表返回全部对局(self, repo):
        await _make_match(repo)
        await _make_match(repo)
        rows = await repo.list_matches()
        assert len(rows) >= 2

    async def test_current_seq与库中最大seq一致(self, repo):
        m = await _make_match(repo)
        await repo.append_event(m["id"], Event(type="t", payload={}))
        await repo.append_event(m["id"], Event(type="t", payload={}))
        got = await repo.get_match(m["id"])
        assert got["current_seq"] == 2


class TestUsageRepo:
    async def test_记录llm调用并按对局汇总(self, repo, usage_repo):
        m = await _make_match(repo)
        await usage_repo.record_call(match_id=m["id"], purpose="speech", model="m1",
                                     prompt_tokens=100, completion_tokens=50,
                                     cost_micros=1000, latency_ms=120, status="ok")
        await usage_repo.record_call(match_id=m["id"], purpose="speech", model="m1",
                                     prompt_tokens=10, completion_tokens=5,
                                     cost_micros=100, latency_ms=30, status="ok")
        summary = await usage_repo.summarize(m["id"])
        assert summary["total_calls"] == 2
        assert summary["prompt_tokens"] == 110
        assert summary["completion_tokens"] == 55
        assert summary["cost_micros"] == 1100

    async def test_失败调用也被记录(self, repo, usage_repo):
        m = await _make_match(repo)
        await usage_repo.record_call(match_id=m["id"], purpose="vote", model="m1",
                                     prompt_tokens=0, completion_tokens=0,
                                     cost_micros=0, latency_ms=60000, status="timeout")
        summary = await usage_repo.summarize(m["id"])
        assert summary["total_calls"] == 1
