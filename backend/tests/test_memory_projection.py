"""记忆投影测试（Red 先行）：按 VisMeta 过滤的本座可见事件历史。

契约见 docs/agents-and-llm.md 第 5 层记忆层：public 全可见、seat 仅成员、god 不可见；
渲染规则属于游戏插件（GameDefinition.memory_line），本文件用真实 WerewolfGame 验证。
"""

import pytest

from app.core import Event, VisMeta
from app.engine.runner import MatchRunner
from app.games.registry import resolve_board
from app.games.werewolf.definition import WerewolfGame
from app.llm.gateway import MockLLM
from app.storage.repo import SqliteMatchRepository

SPEC = resolve_board({"id": "p9-standard"})[1]
SEAT_META = {i: {"model": "mock", "style": "", "strategy": "", "role": "villager"}
             for i in range(1, 10)}


@pytest.fixture()
async def repo(tmp_path):
    r = SqliteMatchRepository(db_path=str(tmp_path / "m.db"))
    await r.init()
    yield r
    await r.close()


def _mk_runner(repo) -> MatchRunner:
    return MatchRunner(match_id=1, game=WerewolfGame(), spec=SPEC, repo=repo,
                       gateway=MockLLM(script=[]), seed=1, seat_meta=dict(SEAT_META))


def _ev(type_: str, payload: dict, vis: VisMeta, day: int = 1, phase: str = "") -> Event:
    return Event(type=type_, payload=payload, day_index=day, phase=phase, vis=vis)


def _mem(runner: MatchRunner, seat: int) -> list[str]:
    return runner._memory_items(seat)


class TestMemoryProjection:
    def test_公开发言全部可见(self, repo):
        runner = _mk_runner(repo)
        runner._events = [
            _ev("player.speech", {"seat": 1, "text": "大家好"}, VisMeta(level="public")),
            _ev("player.speech", {"seat": 2, "text": "我是好人"}, VisMeta(level="public")),
        ]
        # 无状态调用：自己的发言也要进记忆，否则模型会忘记自己说过什么
        expected = ['<speech seat="1">大家好</speech>',
                    '<speech seat="2">我是好人</speech>']
        assert _mem(runner, 1) == expected
        assert _mem(runner, 2) == expected
        assert _mem(runner, 3) == expected

    def test_狼队私聊仅狼可见(self, repo):
        runner = _mk_runner(repo)
        runner._events = [
            _ev("channel.message", {"seat": 1, "text": "今晚刀3"},
                VisMeta(level="seat", seats=[1, 2])),
            _ev("channel.message", {"seat": 2, "text": "刀4更稳"},
                VisMeta(level="seat", seats=[1, 2])),
        ]
        # 狼队成员互相可见（含自己的发言：无状态调用需记住自己定的刀）；外人不可见
        assert _mem(runner, 1) == ['<speech seat="1">今晚刀3</speech>',
                                   '<speech seat="2">刀4更稳</speech>']
        assert _mem(runner, 3) == []

    def test_god级事件对所有人不可见(self, repo):
        runner = _mk_runner(repo)
        runner._events = [
            _ev("player.monologue", {"seat": 1, "text": "内心独白"}, VisMeta(level="god")),
            _ev("night.kill_target", {"target": 3}, VisMeta(level="god")),
            _ev("night.death_cause", {"causes": {"3": "poison"}}, VisMeta(level="god")),
            _ev("night.witch_action", {"seat": 5, "act": "poison", "target": 3},
                VisMeta(level="god")),
        ]
        assert _mem(runner, 1) == []
        assert _mem(runner, 2) == []

    def test_验人结果仅预言家可见(self, repo):
        runner = _mk_runner(repo)
        runner._events = [
            _ev("night.seer_result", {"seat": 3, "target": 5, "verdict": "wolf"},
                VisMeta(level="seat", seats=[3])),
            _ev("night.seer_result", {"seat": 3, "target": 6, "verdict": "good"},
                VisMeta(level="seat", seats=[3])),
        ]
        assert _mem(runner, 3) == ["你查验了 5 号玩家：阵营是【狼人】。",
                                   "你查验了 6 号玩家：阵营是【好人】。"]
        assert _mem(runner, 4) == []

    def test_死讯与放逐结果公开(self, repo):
        runner = _mk_runner(repo)
        runner._events = [
            _ev("night.resolved", {"day": 1, "deaths": {"2": ""}},
                VisMeta(level="public"), day=1),
            _ev("vote.resolved", {"votes": {}, "scope": "exile", "exiled": 3, "tied": []},
                VisMeta(level="public"), day=1),
        ]
        # 死因不进记忆（immersive 不报死因）
        assert _mem(runner, 1) == ["第 1 夜：2 号 死亡。",
                                   "第 1 天放逐投票：3 号出局。"]
        assert "knife" not in "".join(_mem(runner, 1))

    def test_平安夜与平票(self, repo):
        runner = _mk_runner(repo)
        runner._events = [
            _ev("night.resolved", {"day": 1, "deaths": {}}, VisMeta(level="public"), day=1),
            _ev("vote.resolved", {"votes": {}, "scope": "exile", "exiled": None,
                                  "tie": True, "tied": [1, 2]},
                VisMeta(level="public"), day=1),
        ]
        assert _mem(runner, 1) == ["第 1 夜：平安夜，无人死亡。",
                                   "第 1 天放逐投票平票，无人出局。"]

    def test_遗言公开可见(self, repo):
        runner = _mk_runner(repo)
        runner._events = [
            _ev("player.last_words", {"seat": 2, "text": "我预言家走的"},
                VisMeta(level="public")),
        ]
        assert _mem(runner, 1) == ['<speech seat="2">（遗言）我预言家走的</speech>']


class TestMemoryCompleteness:
    """回归 M1：对本人可见的关键公开事件不得被记忆层丢弃。"""

    def test_票型进记忆(self, repo):
        runner = _mk_runner(repo)
        runner._events = [
            _ev("vote.cast", {"seat": 4, "target": 7}, VisMeta(level="public")),
            _ev("vote.cast", {"seat": 5, "target": 0}, VisMeta(level="public")),
        ]
        assert _mem(runner, 1) == ["4 号投给了 7 号。", "5 号弃票。"]

    def test_警徽与上警名单进记忆(self, repo):
        runner = _mk_runner(repo)
        runner._events = [
            _ev("sheriff.registered", {"seats": [1, 4]}, VisMeta(level="public")),
            _ev("sheriff.badge", {"action": "transfer", "to": 4}, VisMeta(level="public")),
        ]
        assert _mem(runner, 2) == ["上警报名：1 号、4 号。", "警徽归属：4 号。"]

    def test_无人上警与撕毁警徽(self, repo):
        runner = _mk_runner(repo)
        runner._events = [
            _ev("sheriff.registered", {"seats": []}, VisMeta(level="public")),
            _ev("sheriff.badge", {"action": "destroy"}, VisMeta(level="public")),
        ]
        assert _mem(runner, 2) == ["上警报名：无人上警。", "警徽被撕毁，本局再无警长。"]

    def test_开枪结果进记忆(self, repo):
        runner = _mk_runner(repo)
        runner._events = [
            _ev("gun.shoot", {"seat": 6, "target": 9}, VisMeta(level="public")),
            _ev("gun.shoot", {"seat": 6, "target": 0}, VisMeta(level="public")),
        ]
        assert _mem(runner, 1) == ["6 号开枪带走了 9 号。", "6 号开枪但未带走任何人。"]

    def test_警长选举票不当作放逐(self, repo):
        runner = _mk_runner(repo)
        runner._events = [
            _ev("vote.resolved", {"votes": {}, "scope": "sheriff", "exiled": 4,
                                  "tie": False, "tied": [4]}, VisMeta(level="public")),
        ]
        assert _mem(runner, 1) == ["警长投票结果：4 号当选警长。"]

    def test_阶段标记进记忆(self, repo):
        runner = _mk_runner(repo)
        runner._events = [
            _ev("phase.started", {"phase": "day_speech", "day": 2},
                VisMeta(level="public"), day=2),
        ]
        assert _mem(runner, 1) == ["【第 2 天·白天发言】"]

    def test_技能状态仅枪手可见(self, repo):
        runner = _mk_runner(repo)
        runner._events = [
            _ev("skill_state.notice", {"seat": 6, "can_shoot": False},
                VisMeta(level="seat", seats=[6])),
        ]
        assert _mem(runner, 6) == ["你的技能状态：今晚不能开枪。"]
        assert _mem(runner, 1) == []

    def test_发言顺序与对局起止进记忆(self, repo):
        """D26 补齐：day.speech_order / match.started / match.finished 也要有落点。"""
        runner = _mk_runner(repo)
        runner._events = [
            _ev("match.started", {"rng_seed": 1}, VisMeta(level="public")),
            _ev("day.speech_order", {"order": [2, 3, 1], "start": 2, "decided_by": "sheriff"},
                VisMeta(level="public")),
            _ev("match.finished", {"winner": "good", "reason": "狼人阵营全部出局"},
                VisMeta(level="public")),
        ]
        assert _mem(runner, 1) == [
            "对局开始。",
            "本轮发言顺序：2 号→3 号→1 号。",
            "对局结束：好人阵营获胜（狼人阵营全部出局）。",
        ]

    def test_刻意不落点的事件(self, repo):
        """role.dealt / night.started / match.created 刻意不进记忆（信息已由其它层给出）。"""
        runner = _mk_runner(repo)
        runner._events = [
            _ev("role.dealt", {"seat": 1, "role": "wolf"}, VisMeta(level="seat", seats=[1])),
            _ev("night.started", {"day": 2}, VisMeta(level="public")),
            _ev("match.created", {"board_id": "p9-standard"}, VisMeta(level="public")),
        ]
        assert _mem(runner, 1) == []
