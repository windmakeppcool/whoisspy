"""rules 纯函数测试（Red 先行）：docs/backend/05-rules.md 全分支。"""

from random import Random

import pytest

from app.events import AskSpec, GameResult
from app.rules import (
    DEATH_KNIFE,
    DEATH_POISON,
    MAX_DAYS,
    ROLES,
    check_winner,
    deal,
    decide_kill,
    neutral_action,
    resolve_night,
    tally_votes,
    validate_action,
)


def _state(**kw):
    """最小可用的状态对象（rules 只依赖属性，不依赖 app.state 模块）。"""
    from types import SimpleNamespace

    st = SimpleNamespace(
        roles=kw.get("roles", {}),
        alive=kw.get("alive", {}),
        day=kw.get("day", 0),
        sheriff=kw.get("sheriff"),
        used_save=kw.get("used_save", False),
        used_poison=kw.get("used_poison", False),
        night=kw.get("night", {}),
    )
    return st


# ---------- 发牌 ----------

def test_发牌组合正确():
    roles = deal(42)
    assert set(roles) == set(range(1, 10))
    from collections import Counter

    assert Counter(roles.values()) == ROLES


def test_发牌同seed复现():
    assert deal(42) == deal(42)


def test_发牌不同seed大概率不同():
    assert deal(42) != deal(43)


# ---------- 定刀 ----------

def test_定刀多数决定():
    # {1:3, 2:3, 3:5} → 3 号得 2 票（1、2 号投），5 号得 1 票
    assert decide_kill({1: 3, 2: 3, 3: 5}, Random(1), {1, 2, 3, 4, 5}) == (3, "majority")


def test_定刀平票rng决胜():
    target, decided = decide_kill({1: 3, 2: 4, 3: 3, 4: 4}, Random(42), {1, 2, 3, 4})
    assert decided == "rng"
    assert target in (3, 4)


def test_定刀全员弃权空刀():
    assert decide_kill({1: 0, 2: 0, 3: 0}, Random(1), {1, 2, 3}) == (None, "empty")


def test_定刀非法目标视作弃权():
    assert decide_kill({1: 99, 2: 0}, Random(1), {1, 2, 3}) == (None, "empty")


def test_定刀空提案空刀():
    assert decide_kill({}, Random(1), {1, 2, 3}) == (None, "empty")


# ---------- 计票 ----------

def test_计票唯一最高出局():
    assert tally_votes({1: 2, 2: 3, 3: 2}) == {"exiled": 2, "tie": False, "tied": [],
                                               "counts": {2: 2, 3: 1}}


def test_计票全弃权无人出局():
    assert tally_votes({1: 0, 2: 0, 3: 0}) == {"exiled": None, "tie": False,
                                               "tied": [], "counts": {}}


def test_计票平票():
    t = tally_votes({1: 2, 2: 3, 3: 2, 4: 3})
    assert t["exiled"] is None and t["tie"] is True
    assert set(t["tied"]) == {2, 3}


def test_计票警长2票权重():
    assert tally_votes({1: 2, 2: 2, 3: 5}, sheriff=1)["exiled"] == 2


def test_计票警长票破解平票():
    assert tally_votes({1: 2, 2: 3, 3: 2}, sheriff=1)["exiled"] == 2


def test_计票counts含警长权重():
    t = tally_votes({1: 2, 2: 2, 3: 5}, sheriff=1)
    assert t["counts"] == {2: 3, 5: 1}  # 警长 1 号投 2 → 2 票权重


# ---------- 夜结算矩阵 ----------

def test_夜结算空刀平安夜():
    assert resolve_night({"kill": None}) == {}


def test_夜结算刀口为0视作空刀():
    assert resolve_night({"kill": 0}) == {}


def test_夜结算单刀死亡():
    assert resolve_night({"kill": 3}) == {3: DEATH_KNIFE}


def test_夜结算刀被救免死():
    assert resolve_night({"kill": 3, "saved": True}) == {}


def test_夜结算毒杀():
    assert resolve_night({"poison": 5}) == {5: DEATH_POISON}


def test_夜结算刀毒不同目标双死():
    assert resolve_night({"kill": 3, "poison": 5}) == {3: DEATH_KNIFE, 5: DEATH_POISON}


def test_夜结算同刀同毒未救算刀杀():
    assert resolve_night({"kill": 3, "poison": 3}) == {3: DEATH_KNIFE}


def test_夜结算同刀同毒已救算毒杀():
    assert resolve_night({"kill": 3, "saved": True, "poison": 3}) == {3: DEATH_POISON}


def test_夜结算空刀加毒():
    assert resolve_night({"kill": None, "poison": 5}) == {5: DEATH_POISON}


# ---------- 胜负 ----------

def _alive_roles(wolves=(1, 2, 3), seer=(4,), witch=(5,), hunter=(6,), villager=(7, 8, 9)):
    roles, alive = {}, {}
    for i, rs in enumerate([wolves, seer, witch, hunter, villager], start=1):
        for s in rs:
            roles[s] = ["wolf", "seer", "witch", "hunter", "villager"][i - 1]
            alive[s] = True
    return roles, alive


def test_胜负好人胜狼全灭():
    roles, alive = _alive_roles(wolves=(), seer=(4,), witch=(5,), hunter=(6,), villager=(7,))
    r = check_winner(_state(roles=roles, alive=alive), day_cycle_done=True)
    assert r == GameResult(winner="good", reason="狼人全部出局")


def test_胜负屠边神职全灭():
    roles, alive = _alive_roles(seer=(), witch=(), hunter=())
    r = check_winner(_state(roles=roles, alive=alive), day_cycle_done=False)
    assert r is not None and r.winner == "wolf"


def test_胜负屠边平民全灭():
    roles, alive = _alive_roles(villager=())
    r = check_winner(_state(roles=roles, alive=alive), day_cycle_done=False)
    assert r is not None and r.winner == "wolf"


def test_胜负屠城狼多于等于好人():
    roles, alive = _alive_roles(wolves=(1, 2), seer=(4,), witch=(), hunter=(), villager=(7,))
    r = check_winner(_state(roles=roles, alive=alive), day_cycle_done=False)
    assert r is not None and r.winner == "wolf"  # 2 狼 vs 2 好


def test_胜负狼少不判():
    roles, alive = _alive_roles(wolves=(1,), seer=(4,), witch=(5,), hunter=(6,), villager=(7,))
    assert check_winner(_state(roles=roles, alive=alive), day_cycle_done=True) is None


def test_胜负时限满max_days白天走完判狼胜():
    roles, alive = _alive_roles()
    st = _state(roles=roles, alive=alive, day=MAX_DAYS)
    r = check_winner(st, day_cycle_done=True)
    assert r is not None and r.winner == "wolf"


def test_胜负时限白天未走完不提前判():
    roles, alive = _alive_roles()
    st = _state(roles=roles, alive=alive, day=MAX_DAYS)
    assert check_winner(st, day_cycle_done=False) is None


def test_胜负max_days前一天不判():
    roles, alive = _alive_roles()
    st = _state(roles=roles, alive=alive, day=MAX_DAYS - 1)
    assert check_winner(st, day_cycle_done=True) is None


# ---------- 动作校验 ----------

def _spec(**kw):
    return AskSpec(action_type=kw.get("action_type", "vote"),
                   prompt="", candidates=kw.get("candidates", [1, 2, 3]))


def test_校验非法类型降级中性():
    st = _state(roles={1: "wolf", 2: "villager"}, alive={1: True, 2: True})
    assert validate_action(st, "day_vote", _spec(), {"type": "kill", "target": 1}) == {
        "type": "vote", "target": 0}


def test_校验target越界降级弃权():
    st = _state(roles={1: "wolf", 2: "villager"}, alive={1: True, 2: True})
    assert validate_action(st, "day_vote", _spec(), {"type": "vote", "target": 5}) == {
        "type": "vote", "target": 0}


def test_校验target死亡降级弃权():
    st = _state(roles={1: "wolf", 2: "villager"}, alive={1: True, 2: False})
    assert validate_action(st, "day_vote", _spec(), {"type": "vote", "target": 2}) == {
        "type": "vote", "target": 0}


def test_校验合法target原样返回():
    st = _state(roles={1: "wolf", 2: "villager"}, alive={1: True, 2: True})
    assert validate_action(st, "day_vote", _spec(), {"type": "vote", "target": 1}) == {
        "type": "vote", "target": 1}


def test_校验女巫空刀夜save降级pass():
    st = _state(roles={1: "witch"}, alive={1: True}, night={})
    got = validate_action(st, "witch_turn",
                          _spec(action_type="save"), {"type": "save", "target": 0})
    assert got == {"type": "pass", "target": 0}


def test_校验女巫解药已用save降级pass():
    st = _state(roles={1: "witch"}, alive={1: True}, night={"kill": 3}, used_save=True)
    got = validate_action(st, "witch_turn",
                          _spec(action_type="save"), {"type": "save", "target": 0})
    assert got == {"type": "pass", "target": 0}


def test_校验女巫正常save():
    st = _state(roles={1: "witch"}, alive={1: True}, night={"kill": 3})
    got = validate_action(st, "witch_turn",
                          _spec(action_type="save"), {"type": "save", "target": 0})
    assert got == {"type": "save", "target": 0}


def test_校验女巫毒药已用降级pass():
    st = _state(roles={1: "witch"}, alive={1: True}, night={}, used_poison=True)
    got = validate_action(st, "witch_turn",
                          _spec(action_type="poison"), {"type": "poison", "target": 2})
    assert got == {"type": "pass", "target": 0}


def test_校验女巫正常毒药():
    st = _state(roles={1: "witch", 2: "villager"}, alive={1: True, 2: True}, night={})
    got = validate_action(st, "witch_turn",
                          _spec(action_type="poison", candidates=[1, 2]),
                          {"type": "poison", "target": 2})
    assert got == {"type": "poison", "target": 2}


def test_校验register布尔化():
    st = _state(roles={1: "wolf"}, alive={1: True})
    got = validate_action(st, "sheriff_register",
                          _spec(action_type="register"), {"type": "register", "yes": "true"})
    assert got == {"type": "register", "yes": True}


def test_校验speech类target恒0():
    st = _state(roles={1: "wolf"}, alive={1: True})
    got = validate_action(st, "day_speech",
                          _spec(action_type="speech"), {"type": "speech", "target": 5})
    assert got == {"type": "speech", "target": 0}


# ---------- 中性兜底 ----------

def test_中性动作全phase():
    expected = {
        "wolf_meeting": {"type": "kill", "target": 0},
        "closing": {"type": "kill", "target": 0},
        "seer_check": {"type": "check", "target": 0},
        "witch_turn": {"type": "pass", "target": 0},
        "speech_order": {"type": "speech_order", "target": 0},
        "ballot": {"type": "vote", "target": 0},
        "day_vote": {"type": "vote", "target": 0},
        "sheriff_register": {"type": "register", "yes": False},
        "last_words": {"type": "speech", "target": 0},
        "serial_speech": {"type": "speech", "target": 0},
        "day_speech": {"type": "speech", "target": 0},
        "gun": {"type": "shoot", "target": 0},
        "badge": {"type": "badge", "target": 0},
    }
    for phase, want in expected.items():
        assert neutral_action(phase) == want, phase


def test_中性动作未知phase默认pass():
    assert neutral_action("unknown") == {"type": "pass", "target": 0}