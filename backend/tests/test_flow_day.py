"""flow 白天流程与主循环测试（Red 先行）：docs/backend/02-flow.md 第四节/二节。"""

import json
from types import SimpleNamespace

import pytest

from app.events import public
from app.flow import MatchRun, _day_vote, _exile_resolve, _speech_order, day_phase, run_match
from app.llm import LLMGateway
from app.state import GameState
from app.store import Store

ROLES9 = {1: "wolf", 2: "wolf", 3: "wolf", 4: "seer", 5: "witch", 6: "hunter",
          7: "villager", 8: "villager", 9: "villager"}


class ScriptedGateway:
    """按 (purpose, seat) 返回脚本化 JSON 回复；未计划的调用直接失败。

    plan 值可为 list[str]：同一 (purpose, seat) 多次调用按次数依次取（如 PK 两轮投票）。
    """

    def __init__(self, plan: dict[tuple[str, int] | str, str | list[str]]):
        self.plan = plan
        self.calls: list[tuple[str, int]] = []

    async def complete(self, *, seat_cfg, messages, purpose, match_id):
        seat_no = int(seat_cfg.get("seat", 0))
        raw = self.plan.get((purpose, seat_no)) or self.plan.get(purpose)
        if raw is None:
            raise RuntimeError(f"unplanned call: {purpose} seat {seat_no}")
        self.calls.append((purpose, seat_no))
        if isinstance(raw, list):
            idx = min(self.calls.count((purpose, seat_no)) - 1, len(raw) - 1)
            raw = raw[idx]
        return SimpleNamespace(raw=raw, usage={}, cost_micros=0, latency_ms=0,
                               status="ok")


def _action(raw_type, target=0, yes=False, **kw):
    d = {"type": raw_type, "target": target}
    if raw_type == "register":
        d = {"type": "register", "yes": yes}
    d.update(kw)
    return json.dumps({"monologue": "m", "speech": "s", "action": d},
                      ensure_ascii=False)


@pytest.fixture
async def run_factory():
    stores: list[Store] = []

    async def _make(seed=42, roles=None, *, gateway=None, sheriff=None,
                    speech_order=None, last_exile=None, last_exile_tied=None,
                    last_exile_was_alive=False, alive=None, max_calls=600,
                    elect_done=False):
        store = await Store.init(":memory:")
        stores.append(store)
        roles = roles or dict(ROLES9)
        st = GameState(roles=roles, alive=alive or {s: True for s in roles})
        st.sheriff = sheriff
        st.elect_done = elect_done  # 白天直调测试用 True；run_match 整局用 False（事件驱动）
        if speech_order is not None:
            st.speech_order = speech_order
        st.last_exile = last_exile
        st.last_exile_tied = last_exile_tied or []
        st.last_exile_was_alive = last_exile_was_alive
        seats = {i: {"seat": i, "role": roles.get(i, ""), "style": "", "strategy": "",
                     "model": "mock", "base_url": "", "api_key": "",
                     "price_per_mtok_in": 0.0, "price_per_mtok_out": 0.0}
                 for i in range(1, 10)}
        gw = gateway or LLMGateway()
        await store.create_match(seed=seed, board={}, seats=list(seats.values()))
        return MatchRun(match_id=1, seed=seed, state=st, seats=seats, gateway=gw,
                        store=store, max_calls=max_calls)

    yield _make
    for st in stores:
        await st.close()


def _types(run):
    return [e.type for e in run.events]


# ---------- 发言定序 ----------

async def test_无警长rng随机起始(run_factory):
    run = await run_factory()
    await _speech_order(run)
    ev = next(e for e in run.events if e.type == "day.speech_order")
    assert ev.payload["decided_by"] == "rng"
    order = ev.payload["order"]
    assert sorted(order) == [1, 2, 3, 4, 5, 6, 7, 8, 9]
    assert ev.payload["start"] in order
    # 环绕序：从 start 起升序
    i = order.index(ev.payload["start"])
    assert order[i:] + order[:i] == order


async def test_警长指定起始(run_factory):
    plan = {("speech_order", 6): _action("speech_order", target=3)}
    run = await run_factory(sheriff=6, gateway=ScriptedGateway(plan))
    await _speech_order(run)
    ev = next(e for e in run.events if e.type == "day.speech_order")
    assert ev.payload["decided_by"] == "sheriff"
    assert ev.payload["start"] == 3
    assert ev.payload["order"] == [3, 4, 5, 6, 7, 8, 9, 1, 2]


async def test_警长指定非法目标回落rng(run_factory):
    plan = {("speech_order", 6): _action("speech_order", target=99)}
    run = await run_factory(sheriff=6, gateway=ScriptedGateway(plan))
    await _speech_order(run)
    ev = next(e for e in run.events if e.type == "day.speech_order")
    assert ev.payload["decided_by"] == "rng"  # 非法目标 → rng 回落


# ---------- 白天发言 ----------

async def test_白天发言按定序串行(run_factory):
    from app.flow import _day_speech

    plan = {("speech", s): _action("speech") for s in range(1, 10)}
    run = await run_factory(speech_order=[5, 1, 2], gateway=ScriptedGateway(plan))
    await _day_speech(run)  # 只测发言：定序已由 state.speech_order 给出
    speeches = [e for e in run.events if e.type == "player.speech"]
    assert [s.payload["seat"] for s in speeches] == [5, 1, 2]  # 按定序
    assert all(s.vis == public() for s in speeches)


# ---------- 放逐投票 ----------

async def test_放逐投票警长2票权重(run_factory):
    # 1、2 投 3，警长 6 投 3 → 3 得 4 票 vs 4 得 2 票
    plan = {("vote", 1): _action("vote", target=3), ("vote", 2): _action("vote", target=3),
            ("vote", 3): _action("vote", target=4), ("vote", 4): _action("vote", target=4),
            ("vote", 6): _action("vote", target=3)}
    run = await run_factory(sheriff=6, gateway=ScriptedGateway(plan))
    await _day_vote(run)
    ev = next(e for e in run.events if e.type == "vote.resolved")
    assert ev.payload["scope"] == "exile"
    assert ev.payload["exiled"] == 3  # 4 票 vs 2 票
    assert run.state.alive[3] is False  # 放逐判死
    # 票按座位升序落库（P3）
    casts = [e for e in run.events if e.type == "vote.cast"]
    assert [c.payload["seat"] for c in casts] == sorted(c.payload["seat"] for c in casts)


async def test_放逐平票PK与平安日(run_factory):
    # 第一轮 3:3 平票 → PK（voters=[1-6,9]）再 3:3 → 平安日
    plan = {
        ("vote", 1): [_action("vote", target=7), _action("vote", target=7)],
        ("vote", 2): [_action("vote", target=7), _action("vote", target=7)],
        ("vote", 3): [_action("vote", target=7), _action("vote", target=8)],
        ("vote", 4): [_action("vote", target=8), _action("vote", target=8)],
        ("vote", 5): [_action("vote", target=8), _action("vote", target=8)],
        ("vote", 6): [_action("vote", target=8), _action("vote", target=0)],
        ("vote", 7): _action("vote", target=0),
        ("vote", 8): _action("vote", target=0),
        ("vote", 9): [_action("vote", target=0), _action("vote", target=7)],
        ("pk_speech", 7): _action("speech"),
        ("pk_speech", 8): _action("speech"),
    }
    for s in range(1, 10):
        plan.setdefault(("speech", s), _action("speech"))  # 白天发言
    run = await run_factory(gateway=ScriptedGateway(plan))
    await day_phase(run)
    resolved = [e for e in run.events if e.type == "vote.resolved"]
    assert len(resolved) == 2
    assert resolved[0].payload["tie"] is True
    assert resolved[1].payload["tie"] is True
    assert resolved[1].payload["exiled"] is None
    # 平安日：无人出局、无遗言
    assert run.state.alive[7] and run.state.alive[8]
    assert "player.last_words" not in _types(run)


async def test_放逐PK后出局有遗言(run_factory):
    # 第一轮 3:3 平票 → PK 7 号 4 票出局 → 遗言
    plan = {
        ("vote", 1): [_action("vote", target=7), _action("vote", target=7)],
        ("vote", 2): [_action("vote", target=7), _action("vote", target=7)],
        ("vote", 3): [_action("vote", target=7), _action("vote", target=7)],
        ("vote", 4): [_action("vote", target=8), _action("vote", target=8)],
        ("vote", 5): [_action("vote", target=8), _action("vote", target=8)],
        ("vote", 6): [_action("vote", target=8), _action("vote", target=8)],
        ("vote", 7): _action("vote", target=0),
        ("vote", 8): _action("vote", target=0),
        ("vote", 9): [_action("vote", target=0), _action("vote", target=7)],
        ("pk_speech", 7): _action("speech"),
        ("pk_speech", 8): _action("speech"),
        ("last_words", 7): _action("speech"),
    }
    for s in range(1, 10):
        plan.setdefault(("speech", s), _action("speech"))
    run = await run_factory(gateway=ScriptedGateway(plan))
    await day_phase(run)
    resolved = [e for e in run.events if e.type == "vote.resolved"]
    assert len(resolved) == 2
    assert resolved[1].payload["exiled"] == 7
    assert run.state.alive[7] is False
    lw = [e for e in run.events if e.type == "player.last_words"]
    assert len(lw) == 1 and lw[0].payload["seat"] == 7


async def test_放逐警长移交警徽(run_factory):
    plan = {("vote", s): _action("vote", target=6) for s in range(1, 10)}
    plan[("vote", 6)] = _action("vote", target=0)  # 自己投自己算弃权？不，投自己
    plan[("vote", 6)] = _action("vote", target=1)
    plan[("last_words", 6)] = _action("speech")
    plan[("badge", 6)] = _action("badge", target=3)
    run = await run_factory(sheriff=6, gateway=ScriptedGateway(plan))
    await day_phase(run)
    badge = [e for e in run.events if e.type == "sheriff.badge"]
    assert badge, "警长被放逐应触发移徽"
    assert badge[-1].payload == {"action": "transfer", "to": 3}
    assert run.state.sheriff == 3


async def test_放逐猎人开枪(run_factory):
    plan = {("vote", s): _action("vote", target=6) for s in range(1, 10)}
    plan[("vote", 6)] = _action("vote", target=0)
    plan[("last_words", 6)] = _action("speech")
    plan[("gun", 6)] = _action("shoot", target=2)
    run = await run_factory(gateway=ScriptedGateway(plan))
    await day_phase(run)
    shoot = [e for e in run.events if e.type == "gun.shoot"]
    assert len(shoot) == 1
    assert shoot[0].payload == {"seat": 6, "target": 2, "text": "s"}
    assert run.state.alive[2] is False


# ---------- 主循环 ----------

async def test_run_match_mock跑完整局(run_factory):
    run = await run_factory()
    result = await run_match(run)
    types = _types(run)
    assert types[0] == "match.created"
    assert "match.started" in types
    assert types.count("role.dealt") == 9
    assert "night.started" in types
    assert "day.speech_order" in types
    assert "vote.resolved" in types
    if result is not None:
        assert "match.finished" in types
        fin = next(e for e in run.events if e.type == "match.finished")
        assert fin.payload["winner"] == result.winner
    else:
        assert "match.stopped" in types
    # seq 严格递增、事件可折叠
    seqs = [e.seq for e in run.events]
    assert seqs == list(range(1, len(seqs) + 1))
    m = await run.store.load_match(run.match_id)
    assert m["status"] in ("finished", "stopped")
    assert m["result"] is not None
    # 结束后的状态与事件折叠一致（winner 由 run_match 直接赋值，非事件驱动，重放后对齐）
    from app.state import GameState as GS

    replay = GS(roles=dict(run.state.roles),
                alive={s: True for s in run.state.roles})  # 开局初始态：全员存活
    for e in run.events:
        replay.apply(e)
    replay.winner = run.state.winner
    assert replay == run.state


async def test_run_match调用数超限stopped(run_factory):
    run = await run_factory(max_calls=5)
    result = await run_match(run)
    assert result is None
    stopped = next(e for e in run.events if e.type == "match.stopped")
    assert "超限" in stopped.payload["reason"]
    m = await run.store.load_match(run.match_id)
    assert m["status"] == "stopped"