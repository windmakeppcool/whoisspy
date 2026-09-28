"""store 测试（Red 先行）：docs/backend/10-storage.md 全规格。"""

import pytest

from app.events import Event, god, public, seat
from app.store import Store


async def _store(tmp_path):
    return await Store.init(str(tmp_path / "t.db"))


def _event(seq, type_="phase.started", payload=None, vis=None):
    return Event(seq=seq, type=type_, day_index=1, phase="night_start",
                 payload=payload or {"phase": "night_start", "day": 1, "label": "入夜"},
                 vis=vis or public())


def _seats(n=3):
    return [{"seat": i, "persona_id": f"p{i}", "style": "s", "strategy": "t",
             "provider_id": "demo", "base_url": "https://x", "api_key_env": "K",
             "model": "mock",
             "price_per_mtok_in": 2.0, "price_per_mtok_out": 8.0,
             "price_per_mtok_cached_in": 0.5} for i in range(1, n + 1)]


async def test_init幂等(tmp_path):
    s1 = await Store.init(str(tmp_path / "t.db"))
    await s1.close()
    s2 = await Store.init(str(tmp_path / "t.db"))  # 第二次不报错
    await s2.close()


async def test_create_match与座位快照(tmp_path):
    store = await _store(tmp_path)
    mid = await store.create_match(
        seed=42,
        board={"roles": {"wolf": 3}, "wolf_meeting_rounds": 2, "max_days": 8,
               "model_assignments": [{"seat": 1, "basis": "random"}]},
        seats=_seats())
    assert mid >= 1
    seats = await store.load_seats(mid)
    assert len(seats) == 3
    assert seats[0]["seat"] == 1
    assert seats[0]["model"] == "mock"
    assert seats[0]["price_per_mtok_in"] == 2.0
    m = await store.load_match(mid)
    assert m["seed"] == 42
    assert m["status"] == "running"
    assert m["board"]["max_days"] == 8
    await store.close()


async def test_append与读回等价(tmp_path):
    store = await _store(tmp_path)
    mid = await store.create_match(seed=1, board={}, seats=_seats())
    evs = [
        _event(1, "match.started", {"seed": 1}),
        _event(2, "night.kill_target", {"target": 5, "decided_by": "majority"}, vis=god()),
        _event(3, "role.dealt", {"seat": 2, "role": "seer"}, vis=seat(2)),
        _event(4, "player.speech", {"seat": 2, "text": "hi"}),
    ]
    for ev in evs:
        await store.append_event(mid, ev)
    loaded = await store.load_events(mid)
    assert [e.seq for e in loaded] == [1, 2, 3, 4]
    assert loaded[0].type == "match.started"
    assert loaded[1].vis == god()
    assert loaded[2].vis == seat(2)
    assert loaded[3].payload["text"] == "hi"
    assert loaded[1].payload["target"] == 5
    await store.close()


async def test_seq唯一约束(tmp_path):
    store = await _store(tmp_path)
    mid = await store.create_match(seed=1, board={}, seats=_seats())
    await store.append_event(mid, _event(1))
    with pytest.raises(Exception):  # sqlite3.IntegrityError
        await store.append_event(mid, _event(1))
    await store.close()


async def test_set_seat_roles回填(tmp_path):
    store = await _store(tmp_path)
    mid = await store.create_match(seed=1, board={}, seats=_seats())
    await store.set_seat_roles(mid, {1: "wolf", 2: "seer", 3: "villager"})
    seats = await store.load_seats(mid)
    assert {s["seat"]: s["role"] for s in seats} == {1: "wolf", 2: "seer", 3: "villager"}
    await store.close()


async def test_finalize_match(tmp_path):
    store = await _store(tmp_path)
    mid = await store.create_match(seed=1, board={}, seats=_seats())
    await store.finalize_match(mid, "finished", {"winner": "good", "reason": "狼人全部出局"})
    m = await store.load_match(mid)
    assert m["status"] == "finished"
    assert m["result"]["winner"] == "good"
    await store.close()


async def test_add_llm_call与用量汇总(tmp_path):
    store = await _store(tmp_path)
    mid = await store.create_match(seed=1, board={}, seats=_seats())
    await store.add_llm_call(match_id=mid, seat=1, purpose="vote", model="mock",
                             prompt_tokens=1000, completion_tokens=100,
                             cached_prompt_tokens=600, cost_micros=1000,
                             latency_ms=50, status="ok")
    await store.add_llm_call(match_id=mid, seat=2, purpose="speech", model="mock",
                             prompt_tokens=800, completion_tokens=20,
                             cached_prompt_tokens=0, cost_micros=0,
                             latency_ms=40, status="ok")
    s = await store.usage_summary(mid)
    assert s["calls"] == 2
    assert s["prompt_tokens"] == 1800
    assert s["completion_tokens"] == 120
    assert s["cached_prompt_tokens"] == 600
    assert s["cost_micros"] == 1000
    assert abs(s["cache_hit_rate"] - 600 / 1800) < 1e-9
    await store.close()


async def test_usage汇总零调用(tmp_path):
    store = await _store(tmp_path)
    mid = await store.create_match(seed=1, board={}, seats=_seats())
    s = await store.usage_summary(mid)
    assert s["calls"] == 0
    assert s["cache_hit_rate"] == 0.0  # 无 prompt 不除零
    await store.close()