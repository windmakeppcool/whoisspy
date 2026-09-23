"""狼人杀规则纯函数测试（Red 先行）。

覆盖 docs/games/werewolf.md 的约定：
- 发牌校验边界（人数/狼数/预数/民数，两 ruleset）
- 计票与平票（含警长 2 票权重）
- 胜负判定（minimal：屠城+时限；standard-12：屠边×2+屠城+时限）
- 夜间结算矩阵（守卫悖论、毒不被挡、同刀同毒）
- 定刀多数决（平票种子可复现、无合规目标=空刀）
"""

from random import Random

import pytest

from app.games.werewolf.rules import (
    ROLE_DEATH_BY_POISON,
    ROLE_WEREWOLF,
    tally_votes,
    decide_kill,
    resolve_night,
    check_winner_minimal,
    check_winner_standard,
    validate_board,
    validate_board_minimal,
    validate_board_standard,
    deal_roles,
)


# ---------- 发牌校验 ----------

class TestValidateBoardMinimal:
    def test_标准6人板通过(self):
        spec = validate_board_minimal({"roles": {"wolf": 2, "seer": 1, "villager": 3}})
        assert spec.player_count == 6

    def test_人数不足6拒绝(self):
        with pytest.raises(ValueError):
            validate_board_minimal({"roles": {"wolf": 1, "villager": 2}})

    def test_人数超过10拒绝(self):
        roles = {"wolf": 3, "villager": 8}
        with pytest.raises(ValueError):
            validate_board_minimal({"roles": roles})

    def test_狼数超过上限拒绝(self):
        with pytest.raises(ValueError):
            validate_board_minimal({"roles": {"wolf": 3, "seer": 1, "villager": 2}})  # 6人狼上限2

    def test_预言家超过2拒绝(self):
        with pytest.raises(ValueError):
            validate_board_minimal({"roles": {"wolf": 1, "seer": 3, "villager": 3}})

    def test_民为0拒绝(self):
        with pytest.raises(ValueError):
            validate_board_minimal({"roles": {"wolf": 2, "seer": 1, "villager": 0}})

    def test_角色总数与人数不符拒绝(self):
        with pytest.raises(ValueError):
            validate_board_minimal({"roles": {"wolf": 2, "seer": 1, "villager": 2, "witch": 1}})


class TestValidateBoardStandard:
    def test_标准12人局通过(self):
        roles = {"wolf": 3, "wolf_king": 1, "seer": 1, "witch": 1, "hunter": 1, "guard": 1, "villager": 4}
        spec = validate_board_standard({"roles": roles})
        assert spec.player_count == 12

    def test_非固定组合拒绝(self):
        with pytest.raises(ValueError):
            validate_board_standard({"roles": {"wolf": 2, "villager": 10}})


# ---------- 发牌 ----------

class TestDeal:
    def test_发牌覆盖全部座位且角色数正确(self):
        from app.core import BoardSpec

        spec = BoardSpec(game_type="werewolf", ruleset="minimal",
                         roles={"wolf": 2, "seer": 1, "villager": 3})
        rng = Random(42)
        assignments = deal_roles(spec, rng, player_count=6)
        assert sorted(a.seat for a in assignments) == [1, 2, 3, 4, 5, 6]
        roles = sorted(a.role for a in assignments)
        assert roles == ["seer", "villager", "villager", "villager", "wolf", "wolf"]

    def test_同种子可复现(self):
        from app.core import BoardSpec

        spec = BoardSpec(game_type="werewolf", ruleset="minimal",
                         roles={"wolf": 2, "seer": 1, "villager": 3})
        a = deal_roles(spec, Random(7), player_count=6)
        b = deal_roles(spec, Random(7), player_count=6)
        assert [(x.seat, x.role) for x in a] == [(x.seat, x.role) for x in b]


# ---------- 计票 ----------

class TestTally:
    def test_普通计票最高票出局(self):
        # voter→target：1/2/4 号投 3 号，3 号投 4 号
        votes = {1: 3, 2: 3, 3: 4, 4: 3}
        result = tally_votes(votes, sheriff=None)
        assert result == {"exiled": 3, "tie": False}

    def test_平票标记(self):
        # 1 号投 2 号、2 号投 1 号 → 各 1 票平票
        votes = {1: 2, 2: 1}
        result = tally_votes(votes, sheriff=None)
        assert result == {"exiled": None, "tie": True}

    def test_警长2票权重(self):
        # 3 号是警长投 2 号（权重 2）：2 号 1+2=3 票 vs 4 号 2 票 → 2 号出局
        votes = {1: 2, 3: 2, 4: 4, 5: 4}
        result = tally_votes(votes, sheriff=3)
        assert result == {"exiled": 2, "tie": False}

    def test_弃权票不计(self):
        # 1 号弃权(0)，2 号投 3 号，3/4 号投 2 号 → 2 号 2 票出局
        votes = {1: 0, 2: 3, 3: 2, 4: 2}
        result = tally_votes(votes, sheriff=None)
        assert result == {"exiled": 2, "tie": False}


# ---------- 定刀多数决 ----------

class TestDecideKill:
    def test_多数决(self):
        # 3 只狼提案 2 号、1 只提案 5 号 → 2 号当选
        target, decided_by = decide_kill({1: 2, 4: 2, 7: 2, 3: 5}, rng=Random(1))
        assert (target, decided_by) == (2, "majority")

    def test_平票用rng且同种子可复现(self):
        a = decide_kill({1: 2, 4: 5}, rng=Random(99))
        b = decide_kill({1: 2, 4: 5}, rng=Random(99))
        assert a == b
        assert a[1] == "tie_rng"

    def test_全弃权为空刀(self):
        target, decided_by = decide_kill({1: 0, 4: 0}, rng=Random(1))
        assert target is None
        assert decided_by == "empty"

    def test_非法目标被过滤(self):
        target, decided_by = decide_kill({1: 99, 4: 3}, rng=Random(1), valid_targets={3, 5})
        assert target == 3


# ---------- 夜间结算矩阵 ----------

def _night_setup(kill, guard=None, saved=False, poison=None):
    """构造结算输入。kill=刀口，guard=守卫目标，saved=女巫是否用解药，poison=毒目标。"""
    return {"kill": kill, "guard": guard, "saved": saved, "poison": poison}


class TestResolveNight:
    def test_裸刀死(self):
        res = resolve_night(_night_setup(kill=5))
        assert res == {"deaths": {5: "knife"}}

    def test_守卫成功免死(self):
        res = resolve_night(_night_setup(kill=5, guard=5))
        assert res["deaths"] == {}

    def test_解药救活(self):
        res = resolve_night(_night_setup(kill=5, saved=True))
        assert res["deaths"] == {}

    def test_同守同救悖论死_死因刀杀(self):
        res = resolve_night(_night_setup(kill=5, guard=5, saved=True))
        assert res == {"deaths": {5: "knife"}}

    def test_毒不被守卫和解药挡(self):
        res = resolve_night(_night_setup(kill=5, guard=5, saved=True, poison=5))
        assert res["deaths"] == {5: ROLE_DEATH_BY_POISON}

    def test_毒另一个人照死(self):
        res = resolve_night(_night_setup(kill=5, guard=5, poison=7))
        assert res["deaths"] == {7: ROLE_DEATH_BY_POISON}

    def test_同刀同毒死因认定刀杀(self):
        res = resolve_night(_night_setup(kill=5, poison=5))
        assert res == {"deaths": {5: "knife"}}

    def test_空刀平安夜(self):
        res = resolve_night(_night_setup(kill=None))
        assert res["deaths"] == {}


# ---------- 胜负 ----------

def _std_alive(wolves=4, seer=1, witch=1, hunter=1, guard=1, villagers=4):
    roles: dict[int, str] = {}
    seat = 1
    for role, n in [("wolf", wolves), ("wolf_king", 0), ("seer", seer), ("witch", witch),
                    ("hunter", hunter), ("guard", guard), ("villager", villagers)]:
        for _ in range(n):
            roles[seat] = role
            seat += 1
    return roles


class TestWinnerMinimal:
    def test_狼全灭好人胜(self):
        roles = {1: "wolf", 2: "wolf", 3: "seer", 4: "villager", 5: "villager", 6: "villager"}
        alive = {1: False, 2: False, 3: True, 4: True, 5: True, 6: True}
        res = check_winner_minimal(roles, alive)
        assert res is not None and res.winner == "good"

    def test_1狼1民狼胜(self):
        roles = {1: "wolf", 2: "villager"}
        alive = {1: True, 2: True}
        res = check_winner_minimal(roles, alive)
        assert res is not None and res.winner == "wolf"

    def test_未分胜负返回None(self):
        roles = {1: "wolf", 2: "seer", 3: "villager", 4: "villager"}
        alive = {1: True, 2: True, 3: True, 4: True}
        assert check_winner_minimal(roles, alive) is None

    def test_天数超限狼胜(self):
        roles = {1: "wolf", 2: "seer", 3: "villager"}
        alive = {1: True, 2: True, 3: True}
        res = check_winner_minimal(roles, alive, day=9, max_days=8)
        assert res is not None and res.winner == "wolf"
        assert "仍有狼存活" in res.reason


class TestWinnerStandard:
    def test_屠城狼胜(self):
        roles = _std_alive()  # 座位1-4狼、5预6女7猎8守、9-12民
        alive = {s: True for s in roles}
        # 杀 3 神职 + 1 民 → 4狼 vs 4好，尚有守卫与 3 民存活 → 走屠城路径
        for s in (5, 6, 7, 9):
            alive[s] = False
        res = check_winner_standard(roles, alive)
        assert res is not None and res.winner == "wolf"
        assert "屠城" in res.reason

    def test_神职全灭屠边狼胜(self):
        roles = _std_alive()
        alive = {s: True for s in roles}
        for s, r in roles.items():
            if r in ("seer", "witch", "hunter", "guard"):
                alive[s] = False
        # 4狼 vs 4民 → 狼数>=好人数也成立，但走屠边理由
        res = check_winner_standard(roles, alive)
        assert res is not None and res.winner == "wolf"
        assert "神职" in res.reason or "屠边" in res.reason or "存活" in res.reason

    def test_平民全灭屠边狼胜(self):
        roles = _std_alive()
        alive = {s: True for s in roles}
        for s, r in roles.items():
            if r == "villager":
                alive[s] = False
        res = check_winner_standard(roles, alive)
        assert res is not None and res.winner == "wolf"

    def test_狼全灭好人胜(self):
        roles = _std_alive()
        alive = {s: r != "wolf" for s, r in roles.items()}
        res = check_winner_standard(roles, alive)
        assert res is not None and res.winner == "good"

    def test_第8天结束狼胜(self):
        roles = _std_alive()
        alive = {s: True for s in roles}
        res = check_winner_standard(roles, alive, day=8, max_days=8)
        assert res is not None and res.winner == "wolf"

    def test_游戏中返回None(self):
        roles = _std_alive()
        alive = {s: True for s in roles}
        alive[1] = False  # 死1民
        assert check_winner_standard(roles, alive, day=2, max_days=8) is None


# ---------- standard-9（标准 9 人局） ----------

class TestValidateBoardStandard9:
    def test_标准9人局通过(self):
        spec = validate_board(
            {"roles": {"wolf": 3, "seer": 1, "witch": 1, "hunter": 1, "villager": 3}},
            "standard-9")
        assert spec.player_count == 9
        assert spec.ruleset == "standard-9"
        assert spec.roles["villager"] == 3

    def test_错误组合拒绝(self):
        # 少民
        with pytest.raises(ValueError):
            validate_board({"roles": {"wolf": 3, "seer": 1, "witch": 1, "hunter": 1,
                                      "villager": 2}}, "standard-9")
        # 多带守卫（standard-9 无守卫）
        with pytest.raises(ValueError):
            validate_board({"roles": {"wolf": 3, "seer": 1, "witch": 1, "guard": 1,
                                      "villager": 3}}, "standard-9")
        # 狼数不对
        with pytest.raises(ValueError):
            validate_board({"roles": {"wolf": 2, "seer": 1, "witch": 1, "hunter": 1,
                                      "villager": 4}}, "standard-9")


class TestWinnerStandard9:
    def test_神职屠边_狼胜(self):
        from app.games.werewolf.rules import check_winner
        roles = {1: "wolf", 2: "wolf", 3: "wolf", 4: "seer", 5: "witch", 6: "hunter",
                 7: "villager", 8: "villager", 9: "villager"}
        # 三神全死，3狼 vs 3民 → 走神职屠边
        alive = {**{s: False for s in (4, 5, 6)},
                 **{s: True for s in (1, 2, 3, 7, 8, 9)}}
        res = check_winner("standard-9", roles, alive, day=3, max_days=8)
        assert res is not None and res.winner == "wolf"
        assert "神职" in res.reason

    def test_狼全灭_好人胜(self):
        from app.games.werewolf.rules import check_winner
        roles = {1: "wolf", 2: "wolf", 3: "wolf", 4: "seer", 5: "witch", 6: "hunter",
                 7: "villager", 8: "villager", 9: "villager"}
        alive = {**{s: False for s in (1, 2, 3)},
                 **{s: True for s in (4, 5, 6, 7, 8, 9)}}
        res = check_winner("standard-9", roles, alive, day=3, max_days=8)
        assert res is not None and res.winner == "good"
