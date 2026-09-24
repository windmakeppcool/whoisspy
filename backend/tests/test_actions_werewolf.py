"""动作校验与中性兜底单测（Red 先行）：S6 目标校验、S3 兜底不替玩家做决定、X2 选举票不判死。

契约见 docs/game-plugin.md：validate_action 是动作合法性的唯一权威；
docs/engine.md：兜底一律取中性动作。
"""

from random import Random

import pytest

from app.core import BoardSpec, Event, VisMeta
from app.games.base import Step
from app.games.registry import resolve_board
from app.games.werewolf.definition import WerewolfGame
from app.games.werewolf.rules import STANDARD9_ROLES


@pytest.fixture()
def game() -> WerewolfGame:
    return WerewolfGame()


@pytest.fixture()
def state(game):
    spec = game.validate_board({"roles": dict(STANDARD9_ROLES)})
    return game.initial_state(spec, game.deal(spec, Random(1)))


def _seat_with(state, role: str) -> int:
    return next(s for s in sorted(state.roles) if state.roles[s] == role)


class TestNeutralAction:
    def test_女巫步兜底是不用药(self, game, state):
        """回归 S3：request.action_type 是 save，但中性动作必须是 pass。"""
        act = game.neutral_action(state, Step(kind="witch_turn"))
        assert act == {"type": "pass", "target": 0}

    @pytest.mark.parametrize("kind,expected", [
        ("ballot", {"type": "vote", "target": 0}),
        ("day_vote", {"type": "vote", "target": 0}),
        ("wolf_meeting", {"type": "kill", "target": 0}),
        ("closing", {"type": "kill", "target": 0}),
        ("seer_check", {"type": "check", "target": 0}),
        ("day_speech", {"type": "speech", "target": 0}),
        ("last_words", {"type": "speech", "target": 0}),
        ("gun", {"type": "shoot", "target": 0}),
        ("badge", {"type": "badge", "target": 0}),
        ("sheriff_register", {"type": "register", "yes": False}),
    ])
    def test_各步骤兜底动作(self, game, state, kind, expected):
        assert game.neutral_action(state, Step(kind=kind)) == expected

    def test_未知步骤兜底为pass(self, game, state):
        assert game.neutral_action(state, Step(kind="whatever")) == {"type": "pass", "target": 0}


class TestValidateAction:
    def test_非法类型降级为中性动作(self, game, state):
        seat = _seat_with(state, "villager")
        assert game.validate_action(state, Step(kind="day_vote"), seat,
                                    {"type": "kill", "target": 3}) == {
            "type": "vote", "target": 0}

    def test_投票目标必须是存活座位(self, game, state):
        voter = _seat_with(state, "villager")
        dead = _seat_with(state, "wolf")
        state.alive[dead] = False
        step = Step(kind="day_vote")
        assert game.validate_action(state, step, voter, {"type": "vote", "target": dead}) == {
            "type": "vote", "target": 0}
        assert game.validate_action(state, step, voter, {"type": "vote", "target": 999}) == {
            "type": "vote", "target": 0}
        assert game.validate_action(state, step, voter, {"type": "vote", "target": 1}) == {
            "type": "vote", "target": 1}

    def test_投票目标非数字降级弃权(self, game, state):
        voter = _seat_with(state, "villager")
        assert game.validate_action(state, Step(kind="ballot"), voter,
                                    {"type": "vote", "target": "3号"}) == {
            "type": "vote", "target": 0}

    def test_狼刀目标必须是存活座位(self, game, state):
        wolf = _seat_with(state, "wolf")
        state.alive[5] = False
        assert game.validate_action(state, Step(kind="closing"), wolf,
                                    {"type": "kill", "target": 5}) == {"type": "kill", "target": 0}

    def test_女巫空刀夜不能用解药(self, game, state):
        witch = _seat_with(state, "witch")
        state.extra["night"] = {"kill": None}
        assert game.validate_action(state, Step(kind="witch_turn"), witch,
                                    {"type": "save", "target": 0}) == {
            "type": "pass", "target": 0}

    def test_女巫有刀口可救人且目标归零(self, game, state):
        witch = _seat_with(state, "witch")
        state.extra["night"] = {"kill": 7}
        assert game.validate_action(state, Step(kind="witch_turn"), witch,
                                    {"type": "save", "target": 0}) == {
            "type": "save", "target": 0}

    def test_女巫解药已用不能再救(self, game, state):
        witch = _seat_with(state, "witch")
        state.extra["night"] = {"kill": 7}
        state.extra["used_save"] = True
        assert game.validate_action(state, Step(kind="witch_turn"), witch,
                                    {"type": "save", "target": 0}) == {
            "type": "pass", "target": 0}

    def test_毒药已用不能再毒(self, game, state):
        witch = _seat_with(state, "witch")
        state.extra["used_poison"] = True
        assert game.validate_action(state, Step(kind="witch_turn"), witch,
                                    {"type": "poison", "target": 3}) == {
            "type": "pass", "target": 0}

    def test_毒已死或不存在座位降级(self, game, state):
        witch = _seat_with(state, "witch")
        dead = _seat_with(state, "villager")
        state.alive[dead] = False
        for bad in (dead, 99, 0):
            assert game.validate_action(state, Step(kind="witch_turn"), witch,
                                        {"type": "poison", "target": bad}) == {
                "type": "pass", "target": 0}

    def test_毒活人放行(self, game, state):
        witch = _seat_with(state, "witch")
        target = _seat_with(state, "wolf")
        assert game.validate_action(state, Step(kind="witch_turn"), witch,
                                    {"type": "poison", "target": target}) == {
            "type": "poison", "target": target}

    def test_开枪与警徽目标校验(self, game, state):
        hunter = _seat_with(state, "hunter")
        dead = _seat_with(state, "villager")
        state.alive[dead] = False
        assert game.validate_action(state, Step(kind="gun"), hunter,
                                    {"type": "shoot", "target": dead}) == {
            "type": "shoot", "target": 0}
        assert game.validate_action(state, Step(kind="badge"), hunter,
                                    {"type": "badge", "target": 77}) == {
            "type": "badge", "target": 0}

    def test_上警报名取布尔且缺省不上警(self, game, state):
        seat = _seat_with(state, "villager")
        step = Step(kind="sheriff_register")
        assert game.validate_action(state, step, seat, {"type": "register", "yes": True}) == {
            "type": "register", "yes": True}
        assert game.validate_action(state, step, seat, {"type": "register"}) == {
            "type": "register", "yes": False}

    def test_发言动作目标归零(self, game, state):
        seat = _seat_with(state, "villager")
        assert game.validate_action(state, Step(kind="day_speech"), seat,
                                    {"type": "speech", "target": 5}) == {
            "type": "speech", "target": 0}


class TestApplySafety:
    """归约安全：幻觉座位/选举票都不得污染 alive 表。"""

    def _ev(self, type_: str, payload: dict) -> Event:
        return Event(type=type_, payload=payload, vis=VisMeta(level="public"))

    def test_警长选举票不判死(self, game, state):
        """回归 X2：scope=sheriff 的 vote.resolved 不是放逐。"""
        game.apply(state, self._ev("vote.resolved",
                                   {"scope": "sheriff", "exiled": 1, "tie": False}))
        assert state.alive[1] is True

    def test_放逐票判死(self, game, state):
        game.apply(state, self._ev("vote.resolved",
                                   {"scope": "exile", "exiled": 2, "tie": False}))
        assert state.alive[2] is False

    def test_缺scope的票不判死(self, game, state):
        """scope 未知（历史事件/脏数据）时宁可不判死。"""
        game.apply(state, self._ev("vote.resolved", {"exiled": 3, "tie": False}))
        assert state.alive[3] is True

    def test_幻影座位不入alive(self, game, state):
        game.apply(state, self._ev("vote.resolved", {"scope": "exile", "exiled": 99}))
        assert 99 not in state.alive
        game.apply(state, self._ev("gun.shoot", {"seat": 1, "target": 99}))
        assert 99 not in state.alive

    def test_幻影死因不入alive(self, game, state):
        game.apply(state, self._ev("night.resolved", {"deaths": {"0": "knife", "3": "knife"}}))
        assert 0 not in state.alive and state.alive[3] is False

    def test_本轮真实死亡才标记(self, game, state):
        """回归（对抗性复核）：last_exile_was_alive 必须是「投票前存活」的迁移标记。"""
        game.apply(state, self._ev("vote.resolved",
                                   {"scope": "exile", "exiled": 4, "tie": False}))
        assert state.extra["last_exile_was_alive"] is True
        assert state.alive[4] is False

        # 已死座位被再次投票：不得被当成「本轮死亡」（否则会重复发遗言/开枪）
        game.apply(state, self._ev("vote.resolved",
                                   {"scope": "exile", "exiled": 4, "tie": False}))
        assert state.extra["last_exile_was_alive"] is False

    def test_初始状态标记为假(self, game, state):
        assert state.extra["last_exile_was_alive"] is False


class TestPhaseDay:
    def test_夜首推进天数与apply一致(self, game, state):
        state.day = 3
        assert game.phase_day(state, Step(kind="night_start")) == 4
        assert game.phase_day(state, Step(kind="day_speech")) == 3

    def test_apply夜首推进天数(self, game, state):
        state.day = 3
        game.apply(state, Event(type="phase.started", payload={"phase": "night_start", "day": 4},
                                vis=VisMeta(level="public")))
        assert state.day == 4


class TestBoardSpecGuard:
    def test_spec必填(self):
        from app.core import BoardSpec as BS

        spec = BS(game_type="werewolf", ruleset="standard-9", roles=dict(STANDARD9_ROLES))
        assert spec.player_count == 9
