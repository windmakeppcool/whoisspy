"""events 模块测试（Red 先行）：事件与可见性模型（docs/backend/03-events.md）。"""

from app.events import AskSpec, Event, GameResult, Vis, god, public, seat


def test_可见性构造器():
    assert public() == Vis(level="public", seats=[])
    assert god() == Vis(level="god", seats=[])
    assert seat(3) == Vis(level="seat", seats=[3])


def test_event_dataclass字段():
    ev = Event(seq=1, type="phase.started", day_index=1, phase="night_start",
               payload={"phase": "night_start", "day": 1, "label": "入夜"},
               vis=public())
    assert ev.seq == 1
    assert ev.type == "phase.started"
    assert ev.day_index == 1
    assert ev.phase == "night_start"
    assert ev.payload["label"] == "入夜"
    assert ev.vis.level == "public"


def test_gameresult字段():
    r = GameResult(winner="good", reason="狼人全部出局")
    assert r.winner == "good"
    assert r.reason == "狼人全部出局"


def test_askspec默认值():
    s = AskSpec(action_type="vote", prompt="请投票", candidates=[1, 2, 3])
    assert s.prompt_extra == ""
    assert s.candidates == [1, 2, 3]