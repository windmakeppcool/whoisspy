"""flow 夜间流程测试（Red 先行）：docs/backend/02-flow.md 第三节 + 警长竞选。"""

import json
from types import SimpleNamespace

import pytest

from app.events import god, public
from app.flow import (
    MatchRun,
    _night_resolve,
    night_phase,
    resolve_deaths,
    sheriff_election,
)
from app.llm import LLMGateway
from app.state import GameState
from app.store import Store

ROLES9 = {1: "wolf", 2: "wolf", 3: "wolf", 4: "seer", 5: "witch", 6: "hunter",
          7: "villager", 8: "villager", 9: "villager"}


class ScriptedGateway:
    """按 (purpose, seat) 返回脚本化 JSON 回复；未计划的调用直接失败。"""

    def __init__(self, plan: dict[tuple[str, int] | str, str]):
        self.plan = plan
        self.calls: list[tuple[str, int]] = []

    async def complete(self, *, seat_cfg, messages, purpose, match_id):
        seat_no = int(seat_cfg.get("seat", 0))
        self.calls.append((purpose, seat_no))
        raw = self.plan.get((purpose, seat_no)) or self.plan.get(purpose)
        if raw is None:
            raise RuntimeError(f"unplanned call: {purpose} seat {seat_no}")
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
    """构造 MatchRun 的工厂；测试结束后自动 close 全部 store（aiosqlite 线程清理）。"""
    stores: list[Store] = []

    async def _make(seed=42, roles=None, *, store=None, gateway=None,
                    sheriff=None, elect_done=False, night=None, max_calls=600,
                    rounds=2):
        if store is None:
            store = await Store.init(":memory:")
            stores.append(store)
        roles = roles or dict(ROLES9)
        st = GameState(roles=roles, alive={s: True for s in roles})
        st.sheriff = sheriff
        st.elect_done = elect_done
        if night is not None:
            st.night = night
        seats = {i: {"seat": i, "role": roles.get(i, ""), "style": "", "strategy": "",
                     "model": "mock", "base_url": "", "api_key": "",
                     "price_per_mtok_in": 0.0, "price_per_mtok_out": 0.0}
                 for i in range(1, 10)}
        gw = gateway or LLMGateway()
        return MatchRun(match_id=1, seed=seed, state=st, seats=seats, gateway=gw,
                        store=store, max_calls=max_calls, wolf_meeting_rounds=rounds)

    yield _make
    for st in stores:
        await st.close()


def _types(run):
    return [e.type for e in run.events]


# ---------- 入夜与狼队 ----------

async def test_夜间完整流程事件序列(run_factory):
    run = await run_factory()
    await night_phase(run)
    types = _types(run)
    assert types[0] == "phase.started"  # night_start
    assert types[1] == "night.started"
    assert "phase.started" in types
    assert "channel.round.started" in types
    assert types.count("channel.message") == 3  # 3 狼各 1 次频道发言（rounds=2）
    assert "channel.round.ended" in types
    assert "night.kill_target" in types
    assert "night.seer_query" in types
    assert "night.seer_result" in types
    assert "night.witch_action" in types
    assert "sheriff.registered" in types  # 第 1 天选举
    assert "sheriff.badge" in types
    assert "night.resolved" in types
    assert "skill_state.notice" in types
    # 定刀与死讯一致
    kill_ev = next(e for e in run.events if e.type == "night.kill_target")
    target = kill_ev.payload["target"]
    resolved = next(e for e in run.events if e.type == "night.resolved")
    # 死亡只可能是刀口（女巫 mock 可能救活 → 平安夜；不会出现刀口之外的死者）
    assert set(resolved.payload["deaths"]) <= {str(target)}
    # 死因：有死亡必有 night.death_cause（女巫 mock 可能救活刀口 → 平安夜无死因）
    causes_ev = [e for e in run.events if e.type == "night.death_cause"]
    if resolved.payload["deaths"]:
        assert causes_ev
    else:
        assert not causes_ev
    # 事件 seq 严格递增
    seqs = [e.seq for e in run.events]
    assert seqs == list(range(1, len(seqs) + 1))
    # 阶段归约正确
    assert run.state.day == 1
    assert run.state.phase == "night_resolve"


async def test_狼队夜聊串行每狼一次(run_factory):
    run = await run_factory(rounds=2)
    await night_phase(run)
    msgs = [e for e in run.events if e.type == "channel.message"]
    assert len(msgs) == 3
    assert [m.payload["seat"] for m in msgs] == [1, 2, 3]  # 座位升序
    assert all(m.vis.level == "seat" for m in msgs)  # 仅狼队可见


async def test_狼队平票rng决胜入事件(run_factory):
    # 7 人：mock 收刀 1→2、2→5、3→1，三票互不相同 → rng 决胜
    run = await run_factory(seed=42, roles={1: "wolf", 2: "wolf", 3: "wolf",
                                            4: "villager", 5: "villager",
                                            6: "villager", 7: "villager"})
    await night_phase(run)
    kill_ev = next(e for e in run.events if e.type == "night.kill_target")
    assert kill_ev.payload["decided_by"] == "rng"
    assert kill_ev.payload["target"] in (1, 2, 5)


async def test_无狼空刀(run_factory):
    run = await run_factory(roles={1: "villager", 2: "seer"})
    await night_phase(run)
    kill_ev = next(e for e in run.events if e.type == "night.kill_target")
    assert kill_ev.payload["decided_by"] == "no_wolf"
    assert kill_ev.payload["target"] is None
    resolved = next(e for e in run.events if e.type == "night.resolved")
    assert resolved.payload["deaths"] == {}  # 平安夜


async def test_无预言家跳过查验(run_factory):
    run = await run_factory(roles={1: "wolf", 5: "witch", 6: "hunter"})
    await night_phase(run)
    assert "night.seer_query" not in _types(run)
    assert "night.witch_action" in _types(run)


async def test_无女巫跳过用药(run_factory):
    run = await run_factory(roles={1: "wolf", 4: "seer"})
    await night_phase(run)
    assert "night.witch_action" not in _types(run)


async def test_女巫空刀夜save降级pass(run_factory):
    run = await run_factory(night={})
    await _night_resolve(run)
    # 手动构造：空刀夜女巫试图 save → 校验降级 pass
    run.state.night = {}
    from app.flow import _witch_turn

    await _witch_turn(run)
    witch_ev = next(e for e in run.events if e.type == "night.witch_action")
    assert witch_ev.payload["act"] == "pass"
    assert run.state.used_save is False  # 解药不消耗


# ---------- 天亮结算与死亡链 ----------

async def test_猎人被刀可开枪(run_factory):
    run = await run_factory(roles={1: "wolf", 6: "hunter", 7: "villager", 8: "villager"})
    run.state.night = {"kill": 6}
    await _night_resolve(run)
    notice = next(e for e in run.events if e.type == "skill_state.notice")
    assert notice.payload == {"seat": 6, "can_shoot": True}
    shoot = next(e for e in run.events if e.type == "gun.shoot")
    assert shoot.payload["seat"] == 6
    assert shoot.payload["target"] == 8  # mock: cands=[1,7,8]，(6*3+5)%3=2 → 8
    assert run.state.alive[8] is False  # 被枪杀者已死


async def test_猎人被毒不能开枪(run_factory):
    run = await run_factory(roles={1: "wolf", 3: "villager", 6: "hunter"})
    run.state.night = {"kill": 3, "poison": 6}
    await _night_resolve(run)
    notice = next(e for e in run.events if e.type == "skill_state.notice")
    assert notice.payload == {"seat": 6, "can_shoot": False}
    assert "gun.shoot" not in _types(run)
    causes = next(e for e in run.events if e.type == "night.death_cause")
    assert causes.payload["causes"][6] == "poison"


async def test_警长被刀开枪后移交警徽(run_factory):
    run = await run_factory(roles={1: "wolf", 6: "hunter", 7: "villager", 8: "villager"},
                         sheriff=6)
    run.state.night = {"kill": 6}
    await _night_resolve(run)
    badge = [e for e in run.events if e.type == "sheriff.badge"]
    assert badge, "警长死亡应触发移徽"
    assert badge[-1].payload["action"] == "transfer"
    assert badge[-1].payload["to"] in (7, 8)
    assert run.state.sheriff == badge[-1].payload["to"]


async def test_被枪杀者不连锁(run_factory):
    # 6 号猎人（警长）被刀 → 开枪打 8 号（猎人）→ 8 号被枪杀不连锁开枪
    run = await run_factory(roles={1: "wolf", 6: "hunter", 7: "villager", 8: "hunter"},
                            sheriff=6)
    run.state.night = {"kill": 6}
    await _night_resolve(run)
    shoots = [e for e in run.events if e.type == "gun.shoot"]
    assert len(shoots) == 1  # 只有 6 号开了一枪
    assert shoots[0].payload["target"] == 8  # mock: cands=[1,7,8]，(6*3+5)%3=2 → 8
    assert run.state.alive[8] is False


async def test_死亡链里移徽给被枪杀警长(run_factory):
    # 6 号猎人开枪打中警长 8 号 → 警徽由 8 号（已死）移交
    run = await run_factory(roles={1: "wolf", 6: "hunter", 7: "villager", 8: "villager"},
                         sheriff=8)
    run.state.night = {"kill": 6}
    await _night_resolve(run)
    badge = [e for e in run.events if e.type == "sheriff.badge"]
    assert len(badge) == 1  # 8 号被枪杀后移交
    assert badge[0].payload["action"] == "transfer"
    assert run.state.sheriff == badge[0].payload["to"]


# ---------- 警长竞选分支 ----------

async def test_警长选举恰一人上警自动当选(run_factory):
    plan = {("sheriff_register", 1): _action("register", yes=True)}
    for s in (2, 3, 4, 5, 6, 7, 8, 9):
        plan[("sheriff_register", s)] = _action("register", yes=False)
    run = await run_factory(gateway=ScriptedGateway(plan))
    await sheriff_election(run)
    badge = [e for e in run.events if e.type == "sheriff.badge"]
    assert badge[-1].payload == {"action": "transfer", "to": 1}
    assert run.state.sheriff == 1
    assert run.state.elect_done is True


async def test_警长选举无人上警丢徽(run_factory):
    plan = {("sheriff_register", s): _action("register", yes=False) for s in range(1, 10)}
    run = await run_factory(gateway=ScriptedGateway(plan))
    await sheriff_election(run)
    badge = [e for e in run.events if e.type == "sheriff.badge"]
    assert badge[-1].payload == {"action": "destroy"}
    assert run.state.sheriff is None


async def test_警长选举全员上警丢徽(run_factory):
    plan = {("sheriff_register", s): _action("register", yes=True) for s in range(1, 10)}
    run = await run_factory(gateway=ScriptedGateway(plan))
    await sheriff_election(run)
    badge = [e for e in run.events if e.type == "sheriff.badge"]
    assert badge[-1].payload == {"action": "destroy"}


async def test_警长选举投票平票PK再平票丢徽(run_factory):
    plan = {
        ("sheriff_register", 1): _action("register", yes=True),
        ("sheriff_register", 2): _action("register", yes=True),
    }
    for s in (3, 4, 5, 6, 7, 8, 9):
        plan[("sheriff_register", s)] = _action("register", yes=False)
    # 竞选宣言
    for s in (1, 2):
        plan[("sheriff_speech", s)] = _action("speech")
    # 第一轮：3,4 投 1；5,6 投 2；7,8,9 弃权 → 2:2 平票
    plan[("sheriff_vote", 3)] = _action("vote", target=1)
    plan[("sheriff_vote", 4)] = _action("vote", target=1)
    plan[("sheriff_vote", 5)] = _action("vote", target=2)
    plan[("sheriff_vote", 6)] = _action("vote", target=2)
    for s in (7, 8, 9):
        plan[("sheriff_vote", s)] = _action("vote", target=0)
    # PK 再投（全体非平票者）：3,4,7 投 1；5,6,8 投 2；9 弃权 → 3:3 再平票
    plan[("sheriff_vote", 3)] = _action("vote", target=1)
    plan[("sheriff_vote", 4)] = _action("vote", target=1)
    plan[("sheriff_vote", 7)] = _action("vote", target=1)
    plan[("sheriff_vote", 5)] = _action("vote", target=2)
    plan[("sheriff_vote", 6)] = _action("vote", target=2)
    plan[("sheriff_vote", 8)] = _action("vote", target=2)
    plan[("sheriff_vote", 9)] = _action("vote", target=0)
    run = await run_factory(gateway=ScriptedGateway(plan))
    await sheriff_election(run)
    resolved = [e for e in run.events if e.type == "vote.resolved"]
    assert len(resolved) == 2
    assert resolved[0].payload["tie"] is True
    assert resolved[1].payload["tie"] is True
    badge = [e for e in run.events if e.type == "sheriff.badge"]
    assert badge[-1].payload == {"action": "destroy"}
    assert run.state.sheriff is None