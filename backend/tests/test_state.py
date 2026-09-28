"""state reducer 测试（Red 先行）：docs/backend/04-state.md 全规则。"""

from app.events import Event, public, seat
from app.state import GameState


def _st(roles=None, alive=None):
    roles = roles or {i: "villager" for i in range(1, 10)}
    return GameState(roles=roles, alive=alive or {i: True for i in roles})


def _ev(type_, payload=None, vis=None):
    return Event(seq=1, type=type_, day_index=1, phase="x",
                 payload=payload or {}, vis=vis or public())


def _night(roles, alive, *, day=1):
    st = _st(roles, alive)
    st.day = day
    st.night = {}
    return st


# ---------- 逐事件语义 ----------

def test_入夜推进天数与阶段():
    st = _st()
    st.apply(_ev("phase.started", {"phase": "night_start", "day": 1}))
    assert st.day == 1
    assert st.phase == "night_start"
    st.apply(_ev("phase.started", {"phase": "wolf_meeting", "day": 1}))
    assert st.day == 1  # 非入夜不推进
    assert st.phase == "wolf_meeting"


def test_night_started清空本夜收集():
    st = _night({1: "wolf", 2: "villager"}, {1: True, 2: True}, day=3)
    st.night = {"kill": 1, "saved": True}
    st.apply(_ev("night.started", {"day": 4}))
    assert st.night == {}


def test_kill_target写入night():
    st = _night({1: "wolf"}, {1: True})
    st.apply(_ev("night.kill_target", {"target": 3, "decided_by": "majority"}))
    assert st.night["kill"] == 3
    st.apply(_ev("night.kill_target", {"target": None, "decided_by": "empty"}))
    assert st.night["kill"] is None


def test_seer_result缓存():
    st = _night({1: "seer"}, {1: True})
    st.apply(_ev("night.seer_result", {"seat": 1, "target": 5, "verdict": "wolf"}))
    assert st.seer_results[5] == "wolf"


def test_witch_save与poison():
    st = _night({1: "witch"}, {1: True})
    st.apply(_ev("night.witch_action", {"seat": 1, "act": "save", "target": 0}))
    assert st.used_save is True and st.night["saved"] is True
    st.apply(_ev("night.witch_action", {"seat": 1, "act": "poison", "target": 2}))
    assert st.used_poison is True and st.night["poison"] == 2


def test_night_resolved判死():
    st = _night({1: "wolf", 2: "villager", 3: "villager"}, {1: True, 2: True, 3: True})
    st.apply(_ev("night.resolved", {"day": 1, "deaths": {"2": ""}}))
    assert st.alive[2] is False
    assert st.alive[1] is True


def test_vote_resolved_exile判死并记录守门标记():
    st = _night({1: "wolf", 2: "villager"}, {1: True, 2: True})
    st.apply(_ev("vote.resolved", {"votes": {1: 2}, "scope": "exile",
                                   "exiled": 2, "tie": False, "tied": []}))
    assert st.alive[2] is False
    assert st.last_exile == 2
    assert st.last_exile_was_alive is True  # 判死前取样


def test_vote_resolved_exile已死者标记False():
    st = _night({1: "wolf", 2: "villager"}, {1: True, 2: False})
    st.apply(_ev("vote.resolved", {"votes": {1: 2}, "scope": "exile",
                                   "exiled": 2, "tie": False, "tied": []}))
    assert st.last_exile == 2
    assert st.last_exile_was_alive is False  # 投票前已死


def test_vote_resolved_sheriff不判死():
    st = _night({1: "wolf", 2: "villager"}, {1: True, 2: True})
    st.apply(_ev("vote.resolved", {"votes": {1: 2}, "scope": "sheriff",
                                   "exiled": 2, "tie": False, "tied": []}))
    assert st.alive[2] is True  # 警长票不判死（历史 bug X2 语义）
    assert st.last_exile is None


def test_vote_resolved_exile平票不判死():
    st = _night({1: "wolf", 2: "villager", 3: "villager"}, {1: True, 2: True, 3: True})
    st.apply(_ev("vote.resolved", {"votes": {1: 2, 3: 3}, "scope": "exile",
                                   "exiled": None, "tie": True, "tied": [2, 3]}))
    assert st.alive[2] is True and st.alive[3] is True
    assert st.last_exile is None
    assert st.last_exile_tied == [2, 3]


def test_gun_shoot判死():
    st = _night({1: "hunter", 2: "wolf"}, {1: True, 2: True})
    st.apply(_ev("gun.shoot", {"seat": 1, "target": 2, "text": ""}))
    assert st.alive[2] is False


def test_sheriff_registered置elect_done():
    st = _st()
    st.apply(_ev("sheriff.registered", {"seats": [1, 2]}))
    assert st.elect_done is True


def test_sheriff_badge转移与撕毁():
    st = _st()
    st.apply(_ev("sheriff.badge", {"action": "transfer", "to": 3}))
    assert st.sheriff == 3
    st.apply(_ev("sheriff.badge", {"action": "destroy"}))
    assert st.sheriff is None


def test_day_speech_order记录():
    st = _st()
    st.apply(_ev("day.speech_order", {"order": [3, 4, 1], "start": 3, "decided_by": "rng"}))
    assert st.speech_order == [3, 4, 1]


def test_无关事件不改状态():
    st = _night({1: "wolf"}, {1: True})
    before = st.snapshot()
    for t, p in [("role.dealt", {"seat": 1, "role": "wolf"}),
                 ("match.started", {"seed": 1}),
                 ("player.speech", {"seat": 1, "text": "hi"}),
                 ("vote.cast", {"seat": 1, "target": 0}),
                 ("player.monologue", {"seat": 1, "text": "m"}),
                 ("player.fallback", {"seat": 1, "reason": "r", "purpose": "p"}),
                 ("rule.error", {"phase": "x", "reason": "r"})]:
        st.apply(_ev(t, p))
    assert st.snapshot() == before


# ---------- 判死防御 ----------

def test_判死防御幻觉座位():
    st = _night({1: "wolf", 2: "villager"}, {1: True, 2: True})
    st.apply(_ev("night.resolved", {"day": 1, "deaths": {"99": ""}}))
    assert 99 not in st.alive
    st.apply(_ev("gun.shoot", {"seat": 1, "target": None, "text": ""}))
    assert st.alive[2] is True


def test_判死防御json字符串键():
    st = _night({1: "wolf", 2: "villager"}, {1: True, 2: True})
    st.apply(_ev("night.resolved", {"day": 1, "deaths": {"2": ""}}))
    assert st.alive[2] is False


# ---------- 折叠一致性（重放 ≡ 现场） ----------

def test_折叠一致性重放事件流得到相同状态():
    roles = {1: "wolf", 2: "seer", 3: "witch", 4: "hunter",
             5: "villager", 6: "villager", 7: "villager"}
    alive = {i: True for i in roles}
    events = [
        _ev("match.started", {"seed": 1}),
        _ev("phase.started", {"phase": "night_start", "day": 1}),
        _ev("night.started", {"day": 1}),
        _ev("night.kill_target", {"target": 4, "decided_by": "majority", "proposals": {1: 4}}),
        _ev("night.seer_result", {"seat": 2, "target": 1, "verdict": "wolf"}),
        _ev("night.witch_action", {"seat": 3, "act": "pass", "target": 0}),
        _ev("phase.started", {"phase": "night_resolve", "day": 1}),
        _ev("night.resolved", {"day": 1, "deaths": {"4": ""}}),
        _ev("phase.started", {"phase": "speech_order", "day": 1}),
        _ev("day.speech_order", {"order": [1, 2, 3, 5, 6, 7], "start": 1, "decided_by": "rng"}),
        _ev("phase.started", {"phase": "day_vote", "day": 1}),
        _ev("vote.cast", {"seat": 1, "target": 5}),
        _ev("vote.resolved", {"votes": {1: 5, 2: 5, 3: 6, 5: 1, 6: 1, 7: 5},
                              "scope": "exile", "exiled": 5, "tie": False, "tied": []}),
    ]
    # 现场：逐条 apply
    live = GameState(roles=roles, alive=dict(alive))
    for e in events:
        live.apply(e)
    # 重放：全新状态再 apply 一遍 → 必须逐字段一致
    replay = GameState(roles=roles, alive=dict(alive))
    for e in events:
        replay.apply(e)
    assert replay == live
    assert replay.snapshot() == live.snapshot()


def test_apply不修改事件对象():
    e = _ev("night.kill_target", {"target": 3, "decided_by": "majority"})
    payload_before = dict(e.payload)
    st = _night({1: "wolf"}, {1: True})
    st.apply(e)
    assert e.payload == payload_before