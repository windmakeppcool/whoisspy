"""狼人杀规则纯函数测试（唯一板子 standard-9，Red 先行）。

覆盖 docs/games/werewolf.md（单板收敛见 D23）：
- 板子校验：只接受 3狼+预女猎+3民，其他 ruleset/组合一律拒绝
- 发牌：9 座覆盖、同种子可复现
- 计票：最高票/平票（含 tied）/警长 2 票权重/弃权不计
- 定刀：多数决/平票 rng/空刀/非法目标过滤
- 夜间结算：解药只挡刀、毒不被挡、同刀同毒死因、空刀（含 kill=0）平安夜
- 胜负：神职屠边/平民屠边/屠城/狼全灭/时限（必须白天真的走完）
"""

from random import Random

import pytest

from app.core import BoardSpec
from app.games.werewolf.rules import (
    DEATH_BY_KNIFE,
    DEATH_BY_POISON,
    PLAYER_COUNT,
    RULESET,
    STANDARD9_ROLES,
    check_winner,
    deal_roles,
    decide_kill,
    resolve_night,
    tally_votes,
    validate_board,
)

VALID_BOARD = {"ruleset": RULESET, "roles": dict(STANDARD9_ROLES)}

ROLES_9 = {1: "wolf", 2: "wolf", 3: "wolf", 4: "seer", 5: "witch", 6: "hunter",
           7: "villager", 8: "villager", 9: "villager"}


def alive_all() -> dict[int, bool]:
    return {s: True for s in ROLES_9}


# ---------- 板子校验 ----------

class TestValidateBoard:
    def test_标准9人局通过(self):
        spec = validate_board(dict(VALID_BOARD))
        assert spec.player_count == PLAYER_COUNT == 9
        assert spec.ruleset == RULESET
        assert spec.roles == STANDARD9_ROLES

    def test_可调轮次与天数上限(self):
        cfg = {**VALID_BOARD, "wolf_meeting_rounds": 3, "max_days": 12}
        spec = validate_board(cfg)
        assert (spec.wolf_meeting_rounds, spec.max_days) == (3, 12)

    def test_缺省轮次天数(self):
        spec = validate_board(dict(VALID_BOARD))
        assert (spec.wolf_meeting_rounds, spec.max_days) == (2, 8)

    @pytest.mark.parametrize("roles", [
        {"wolf": 3, "seer": 1, "witch": 1, "hunter": 1, "villager": 2},          # 少一民
        {"wolf": 3, "seer": 1, "witch": 1, "hunter": 1, "guard": 1, "villager": 3},  # 多守卫
        {"wolf": 2, "seer": 1, "witch": 1, "hunter": 1, "villager": 4},          # 狼数不对
        {"wolf": 3, "seer": 1, "witch": 1, "hunter": 1, "villager": 3, "wolf_king": 1},  # 多狼王
        {"wolf": 3, "seer": 2, "witch": 1, "hunter": 1, "villager": 2},          # 双预言家
        {},
    ])
    def test_非固定组合一律拒绝(self, roles):
        with pytest.raises(ValueError):
            validate_board({"ruleset": RULESET, "roles": roles})

    def test_角色数量为负拒绝(self):
        with pytest.raises(ValueError):
            validate_board({"ruleset": RULESET,
                            "roles": {**STANDARD9_ROLES, "villager": -1}})

    @pytest.mark.parametrize("ruleset", ["minimal", "standard-12", "whatever", ""])
    def test_其他ruleset拒绝(self, ruleset):
        with pytest.raises(ValueError):
            validate_board({"ruleset": ruleset, "roles": dict(STANDARD9_ROLES)})

    def test_非法轮次与天数拒绝(self):
        with pytest.raises(ValueError):
            validate_board({**VALID_BOARD, "wolf_meeting_rounds": -1})
        with pytest.raises(ValueError):
            validate_board({**VALID_BOARD, "max_days": 0})


# ---------- 发牌 ----------

class TestDeal:
    def test_发牌覆盖9座且角色数正确(self):
        spec = validate_board(dict(VALID_BOARD))
        assignments = deal_roles(spec, Random(42))
        assert sorted(a.seat for a in assignments) == list(range(1, 10))
        counts: dict[str, int] = {}
        for a in assignments:
            counts[a.role] = counts.get(a.role, 0) + 1
        assert counts == STANDARD9_ROLES

    def test_同种子可复现(self):
        spec = validate_board(dict(VALID_BOARD))
        a = deal_roles(spec, Random(7))
        b = deal_roles(spec, Random(7))
        assert [(x.seat, x.role) for x in a] == [(x.seat, x.role) for x in b]


# ---------- 计票 ----------

class TestTally:
    def test_最高票出局(self):
        assert tally_votes({1: 3, 2: 3, 3: 4, 4: 3}) == {
            "exiled": 3, "tie": False, "tied": [3]}

    def test_平票返回并列席位(self):
        assert tally_votes({1: 2, 2: 1}) == {"exiled": None, "tie": True, "tied": [1, 2]}

    def test_警长2票权重(self):
        # 3 号是警长投 2 号（权重 2）：2 号 1+2=3 票 vs 4 号 2 票
        assert tally_votes({1: 2, 3: 2, 4: 4, 5: 4}, sheriff=3) == {
            "exiled": 2, "tie": False, "tied": [2]}

    def test_弃权不计票(self):
        assert tally_votes({1: 0, 2: 3, 3: 2, 4: 2}) == {
            "exiled": 2, "tie": False, "tied": [2]}

    def test_全员弃权为平票且无并列(self):
        assert tally_votes({1: 0, 2: 0}) == {"exiled": None, "tie": True, "tied": []}


# ---------- 定刀多数决 ----------

class TestDecideKill:
    def test_多数决(self):
        assert decide_kill({1: 2, 4: 2, 7: 2, 3: 5}, rng=Random(1)) == (2, "majority")

    def test_平票用rng且同种子可复现(self):
        a = decide_kill({1: 2, 4: 5}, rng=Random(99))
        b = decide_kill({1: 2, 4: 5}, rng=Random(99))
        assert a == b
        assert a[1] == "tie_rng"

    def test_全弃权为空刀(self):
        assert decide_kill({1: 0, 4: 0}, rng=Random(1)) == (None, "empty")

    def test_非法目标被过滤(self):
        assert decide_kill({1: 99, 4: 3}, rng=Random(1), valid_targets={3, 5}) == (3, "majority")


# ---------- 夜间结算 ----------

class TestResolveNight:
    def test_裸刀死(self):
        assert resolve_night({"kill": 5}) == {"deaths": {5: DEATH_BY_KNIFE}}

    def test_解药救活(self):
        assert resolve_night({"kill": 5, "saved": True})["deaths"] == {}

    def test_毒不被解药挡(self):
        assert resolve_night({"kill": 5, "saved": True, "poison": 5})["deaths"] == {
            5: DEATH_BY_POISON}

    def test_毒另一个人照死(self):
        assert resolve_night({"kill": 5, "poison": 7})["deaths"] == {
            5: DEATH_BY_KNIFE, 7: DEATH_BY_POISON}

    def test_同刀同毒未救为刀杀(self):
        assert resolve_night({"kill": 5, "poison": 5})["deaths"] == {5: DEATH_BY_KNIFE}

    def test_同刀同毒已救仍死于毒(self):
        assert resolve_night({"kill": 5, "saved": True, "poison": 5})["deaths"] == {
            5: DEATH_BY_POISON}

    def test_空刀平安夜(self):
        assert resolve_night({"kill": None})["deaths"] == {}

    def test_kill为0也当空刀(self):
        """回归：0 是空刀哨兵，不能与守卫/解药组合出「0 号死亡」。"""
        assert resolve_night({"kill": 0, "saved": True})["deaths"] == {}
        assert resolve_night({"kill": 0, "poison": 3})["deaths"] == {3: DEATH_BY_POISON}

    def test_只毒不刀(self):
        assert resolve_night({"poison": 4})["deaths"] == {4: DEATH_BY_POISON}


# ---------- 胜负 ----------

class TestWinner:
    def test_狼全灭好人胜(self):
        alive = {s: r != "wolf" for s, r in ROLES_9.items()}
        res = check_winner(ROLES_9, alive)
        assert res is not None and res.winner == "good"

    def test_神职屠边狼胜(self):
        alive = alive_all()
        for s in (4, 5, 6):
            alive[s] = False
        res = check_winner(ROLES_9, alive, day=3)
        assert res is not None and res.winner == "wolf"
        assert "神职" in res.reason

    def test_平民屠边狼胜(self):
        alive = alive_all()
        for s in (7, 8, 9):
            alive[s] = False
        res = check_winner(ROLES_9, alive, day=3)
        assert res is not None and res.winner == "wolf"
        assert "平民" in res.reason

    def test_屠城狼胜(self):
        alive = alive_all()
        for s in (4, 5, 7):  # 死 2 神 + 1 民 → 3 狼 vs 3 好（神职/平民都还有人）
            alive[s] = False
        res = check_winner(ROLES_9, alive, day=3)
        assert res is not None and res.winner == "wolf"
        assert "屠城" in res.reason

    def test_未分胜负返回None(self):
        alive = alive_all()
        alive[7] = False  # 死 1 民，3狼 vs 5好
        assert check_winner(ROLES_9, alive, day=2, max_days=8) is None

    def test_时限必须等白天走完(self):
        """回归 M4：第 8 天白天没打完不能判时限狼胜。"""
        alive = alive_all()
        assert check_winner(ROLES_9, alive, day=8, max_days=8, day_cycle_done=False) is None
        res = check_winner(ROLES_9, alive, day=8, max_days=8, day_cycle_done=True)
        assert res is not None and res.winner == "wolf"
        assert "第 8 天白天结束" in res.reason

    def test_未到上限不触发时限(self):
        alive = alive_all()
        assert check_winner(ROLES_9, alive, day=7, max_days=8, day_cycle_done=True) is None

    def test_好人胜优先于时限(self):
        alive = {s: r != "wolf" for s, r in ROLES_9.items()}
        res = check_winner(ROLES_9, alive, day=8, max_days=8, day_cycle_done=True)
        assert res is not None and res.winner == "good"


# ---------- BoardSpec 自洽 ----------

def test_rolespec与固定组合一致():
    spec = BoardSpec(game_type="werewolf", ruleset=RULESET, roles=dict(STANDARD9_ROLES))
    assert spec.player_count == PLAYER_COUNT
    assert sorted(spec.role_list) == sorted(
        ["wolf"] * 3 + ["seer", "witch", "hunter"] + ["villager"] * 3)
