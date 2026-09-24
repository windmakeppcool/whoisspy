"""记忆投影测试（Red 先行）：按 VisMeta 过滤的本座可见事件历史。

契约见 docs/agents-and-llm.md 第 5 层记忆层：public 全可见、seat 仅成员、god 不可见。
"""

import pytest

from app.core import Event, VisMeta
from app.engine.runner import MatchRunner
from app.llm.gateway import MockLLM
from app.storage.repo import SqliteMatchRepository

SEAT_META = {i: {"model": "mock", "style": "", "strategy": "", "role": "villager"}
             for i in range(1, 7)}


@pytest.fixture()
async def repo(tmp_path):
    r = SqliteMatchRepository(db_path=str(tmp_path / "m.db"))
    await r.init()
    yield r
    await r.close()


def _mk_runner(repo) -> MatchRunner:
    return MatchRunner(match_id=1, game=None, spec=None, repo=repo,
                       gateway=MockLLM(script=[]), seed=1, seat_meta=dict(SEAT_META))


def _ev(type_: str, payload: dict, vis: VisMeta, day: int = 1) -> Event:
    return Event(type=type_, payload=payload, day_index=day, phase="", vis=vis)


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
        assert _mem(runner, 1) == ['<speech seat="1">大家好</speech>',
                                   '<speech seat="2">我是好人</speech>']
        assert _mem(runner, 2) == ['<speech seat="1">大家好</speech>',
                                   '<speech seat="2">我是好人</speech>']
        assert _mem(runner, 3) == ['<speech seat="1">大家好</speech>',
                                   '<speech seat="2">我是好人</speech>']

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
        assert _mem(runner, 2) == ['<speech seat="1">今晚刀3</speech>',
                                   '<speech seat="2">刀4更稳</speech>']
        assert _mem(runner, 3) == []

    def test_god级事件对所有人不可见(self, repo):
        runner = _mk_runner(repo)
        runner._events = [
            _ev("player.monologue", {"seat": 1, "text": "内心独白"}, VisMeta(level="god")),
            _ev("night.kill_target", {"target": 3}, VisMeta(level="god")),
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
            _ev("night.resolved", {"day": 1, "deaths": {"2": "knife"}},
                VisMeta(level="public"), day=1),
            _ev("vote.resolved", {"votes": {}, "exiled": 3, "tied": []},
                VisMeta(level="public"), day=1),
        ]
        assert _mem(runner, 1) == ["第 1 夜，2号 死亡。",
                                   "第 1 天放逐投票：3 号玩家出局。"]

    def test_平票无人出局(self, repo):
        runner = _mk_runner(repo)
        runner._events = [
            _ev("vote.resolved", {"votes": {}, "exiled": None, "tie": True, "tied": [1, 2]},
                VisMeta(level="public"), day=1),
        ]
        assert _mem(runner, 1) == ["第 1 天放逐投票：平票，无人出局。"]

    def test_遗言公开可见(self, repo):
        runner = _mk_runner(repo)
        runner._events = [
            _ev("player.last_words", {"seat": 2, "text": "我预言家走的"},
                VisMeta(level="public")),
        ]
        assert _mem(runner, 1) == ['<speech seat="2">（遗言）我预言家走的</speech>']