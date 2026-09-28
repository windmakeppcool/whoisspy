"""flow e2e 确定性验收（Red 先行）：docs/backend/13-testing.md 三。

验收基线：mock 同 seed 两次运行事件流逐字节一致（P3）；多 seed 覆盖狼胜/好人胜；
单局耗时 < 5s；护栏触发 stopped。
"""

import json
import time

import pytest

from app.flow import MatchRun, run_match
from app.llm import LLMGateway
from app.state import GameState
from app.store import Store

ROLES9 = {1: "wolf", 2: "wolf", 3: "wolf", 4: "seer", 5: "witch", 6: "hunter",
          7: "villager", 8: "villager", 9: "villager"}


@pytest.fixture
async def run_factory():
    stores: list[Store] = []

    async def _make(seed=42, max_calls=600):
        store = await Store.init(":memory:")
        stores.append(store)
        st = GameState(roles=dict(ROLES9), alive={s: True for s in ROLES9})
        seats = {i: {"seat": i, "role": "", "style": "", "strategy": "",
                     "model": "mock", "base_url": "", "api_key": "",
                     "price_per_mtok_in": 0.0, "price_per_mtok_out": 0.0}
                 for i in range(1, 10)}
        await store.create_match(seed=seed, board={}, seats=list(seats.values()))
        run = MatchRun(match_id=1, seed=seed, state=st, seats=seats,
                       gateway=LLMGateway(), store=store, max_calls=max_calls)
        return run

    yield _make
    for st in stores:
        await st.close()


def _event_json(run) -> str:
    return json.dumps([{"type": e.type, "payload": e.payload} for e in run.events],
                      ensure_ascii=False, sort_keys=True)


async def test_同seed两次运行事件流逐字节一致(run_factory):
    r1 = await run_factory(seed=42)
    res1 = await run_match(r1)
    r2 = await run_factory(seed=42)
    res2 = await run_match(r2)
    assert _event_json(r1) == _event_json(r2)  # P3：同 seed 逐字节复现
    assert res1 == res2
    assert res1 is not None  # 默认配置应能分出胜负


async def test_不同seed覆盖狼胜与好人胜(run_factory):
    results: set[str] = set()
    for seed in range(12):
        run = await run_factory(seed=seed)
        result = await run_match(run)
        results.add(result.winner if result else "stopped")
    assert "good" in results
    assert "wolf" in results


async def test_单局mock耗时小于5秒(run_factory):
    run = await run_factory(seed=7)
    start = time.monotonic()
    result = await run_match(run)
    elapsed = time.monotonic() - start
    assert result is not None
    assert elapsed < 5.0, f"mock 单局耗时 {elapsed:.2f}s 超过验收基线 5s"


async def test_调用数护栏触发stopped(run_factory):
    run = await run_factory(seed=1, max_calls=8)
    result = await run_match(run)
    assert result is None
    stopped = next(e for e in run.events if e.type == "match.stopped")
    assert "超限" in stopped.payload["reason"]