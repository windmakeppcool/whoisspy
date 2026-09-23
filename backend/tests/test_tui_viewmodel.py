"""ViewModel 投影测试：事件 → 终端显示模型。"""

import pytest
from app.core import Event, VisMeta
from app.tui.viewmodel import MatchVM, apply_event


def make_event(etype: str, payload: dict, day: int = 1, phase: str = "") -> Event:
    return Event(type=etype, payload=payload, day_index=day, phase=phase,
                 vis=VisMeta(level="public"))


def test_初始化空VM():
    """验证空 ViewModel。"""
    vm = MatchVM()
    assert vm.phase == "idle"
    assert vm.day == 0
    assert vm.label == "等待开局"
    assert vm.feed == []
    assert vm.seats == []


def test_阶段事件更新():
    """验证 phase.started 事件更新阶段。"""
    vm = MatchVM()
    ev = make_event("phase.started", {"phase": "day_speech", "day": 1}, day=1, phase="day_speech")
    vm = apply_event(vm, ev, god_view=True)

    assert vm.day == 1
    assert vm.phase == "day"
    assert vm.label == "白天发言"


def test_发言事件追加到feed():
    """验证 player.speech 追加到对话流。"""
    vm = MatchVM()
    ev = make_event("player.speech", {"seat": 1, "text": "你好"}, day=1, phase="day_speech")
    vm = apply_event(vm, ev, god_view=True)

    assert len(vm.feed) == 1
    assert vm.feed[0]["type"] == "speech"
    assert vm.feed[0]["speaker"] == 1
    assert vm.feed[0]["text"] == "你好"


def test_上帝视角显示独白():
    """验证 god_view=True 时显示独白。"""
    vm = MatchVM()
    ev = make_event("player.monologue", {"seat": 1, "text": "我是狼"}, day=1, phase="night")
    vm = apply_event(vm, ev, god_view=True)

    assert len(vm.feed) == 1
    assert vm.feed[0]["type"] == "monologue"


def test_沉浸视角过滤独白():
    """验证 god_view=False 时过滤独白。"""
    vm = MatchVM()
    ev = make_event("player.monologue", {"seat": 1, "text": "我是狼"}, day=1, phase="night")
    vm = apply_event(vm, ev, god_view=False)

    assert len(vm.feed) == 0


def test_发牌事件填充座次表():
    """验证 role.dealt 投影出座次表（座位/角色/存活）。"""
    vm = MatchVM()
    ev = Event(type="role.dealt", payload={"seat": 3, "role": "wolf"},
               day_index=0, phase="", vis=VisMeta(level="seat", seats=[3]))
    vm = apply_event(vm, ev, god_view=True)

    assert len(vm.seats) == 1
    assert vm.seats[0]["seat"] == 3
    assert vm.seats[0]["role"] == "wolf"
    assert vm.seats[0]["alive"] is True


def test_发牌事件多座位按座位号排序():
    """验证多次 role.dealt 累积且按座位号排序。"""
    vm = MatchVM()
    for seat, role in [(2, "villager"), (1, "seer"), (3, "wolf")]:
        ev = Event(type="role.dealt", payload={"seat": seat, "role": role},
                   day_index=0, phase="", vis=VisMeta(level="seat", seats=[seat]))
        vm = apply_event(vm, ev, god_view=True)

    assert [s["seat"] for s in vm.seats] == [1, 2, 3]
    assert vm.seats[0]["role"] == "seer"


def test_发牌事件上帝视角与沉浸视角都填充座次():
    """role.dealt 是座位级可见性：沉浸视角也维护座次表，角色由渲染层隐藏。"""
    vm = MatchVM()
    ev = Event(type="role.dealt", payload={"seat": 1, "role": "wolf"},
               day_index=0, phase="", vis=VisMeta(level="seat", seats=[1]))
    vm = apply_event(vm, ev, god_view=False)

    assert len(vm.seats) == 1
    assert vm.seats[0]["role"] == "wolf"  # 数据在 VM 中，渲染层 render_seats 按视角隐藏


def test_夜间结算更新存活_引擎deaths载荷():
    """验证 night.resolved 的 deaths 载荷（引擎真实格式）标记死亡并播报。"""
    vm = MatchVM(seats=[
        {"seat": 1, "role": "wolf", "alive": True},
        {"seat": 2, "role": "villager", "alive": True},
    ])
    ev = make_event("night.resolved", {"day": 1, "deaths": {2: "knife"}})
    vm = apply_event(vm, ev, god_view=True)

    assert vm.seats[0]["alive"] is True
    assert vm.seats[1]["alive"] is False
    assert any("昨夜死亡" in f.get("text", "") and "2号" in f.get("text", "")
               for f in vm.feed)


def test_夜间结算平安夜不改存活():
    """验证无死亡时不改存活并播报平安夜。"""
    vm = MatchVM(seats=[{"seat": 1, "role": "wolf", "alive": True}])
    ev = make_event("night.resolved", {"day": 1, "deaths": {}})
    vm = apply_event(vm, ev, god_view=True)

    assert vm.seats[0]["alive"] is True
    assert any(f.get("text") == "昨夜平安夜" for f in vm.feed)


def test_夜间结算deaths键为字符串时也能标记():
    """SSE JSON 反序列化后 deaths 的键是字符串，需兼容。"""
    vm = MatchVM(seats=[{"seat": 5, "role": "villager", "alive": True}])
    ev = make_event("night.resolved", {"day": 1, "deaths": {"5": "poison"}})
    vm = apply_event(vm, ev, god_view=True)

    assert vm.seats[0]["alive"] is False


def test_放逐结算更新存活():
    """验证 vote.resolved 的 exiled 座位标记死亡。"""
    vm = MatchVM(seats=[
        {"seat": 3, "role": "villager", "alive": True},
        {"seat": 4, "role": "wolf", "alive": True},
    ])
    ev = make_event("vote.resolved", {"votes": {1: 3}, "title": "放逐投票",
                                      "tied": [], "exiled": 3, "tie": False})
    vm = apply_event(vm, ev, god_view=True)

    assert vm.seats[0]["alive"] is False
    assert vm.seats[1]["alive"] is True


def test_放逐平票不改存活():
    """验证平票（exiled=None）不改存活。"""
    vm = MatchVM(seats=[{"seat": 3, "role": "villager", "alive": True}])
    ev = make_event("vote.resolved", {"votes": {}, "title": "放逐投票",
                                      "tied": [3], "exiled": None, "tie": True})
    vm = apply_event(vm, ev, god_view=True)

    assert vm.seats[0]["alive"] is True


def test_沉浸视角过滤上帝级事件():
    """沉浸视角不得出现 night.kill_target（god 级）——filtered_view 语义。"""
    vm = MatchVM()
    ev = make_event("night.kill_target", {"target": 3})
    ev.vis = VisMeta(level="god")
    vm = apply_event(vm, ev, god_view=False)

    assert vm.feed == []


def test_沉浸视角过滤座位级频道消息():
    """沉浸视角不得出现 channel.message（seat 级）。"""
    vm = MatchVM()
    ev = make_event("channel.message", {"seat": 1, "text": "刀3号"})
    ev.vis = VisMeta(level="seat", seats=[1, 2])
    vm = apply_event(vm, ev, god_view=False)

    assert vm.feed == []


def test_上帝视角保留上帝级与座位级事件():
    """上帝视角全量可见。"""
    vm = MatchVM()
    ev_kill = make_event("night.kill_target", {"target": 3})
    ev_kill.vis = VisMeta(level="god")
    vm = apply_event(vm, ev_kill, god_view=True)

    ev_chan = make_event("channel.message", {"seat": 1, "text": "刀3号"})
    ev_chan.vis = VisMeta(level="seat", seats=[1, 2])
    vm = apply_event(vm, ev_chan, god_view=True)

    assert len(vm.feed) == 2


def test_沉浸视角公开事件正常投影():
    """公开事件（发言/阶段）沉浸视角不受过滤影响。"""
    vm = MatchVM()
    ev = make_event("player.speech", {"seat": 2, "text": "我是好人"})
    ev.vis = VisMeta(level="public")
    vm = apply_event(vm, ev, god_view=False)

    assert len(vm.feed) == 1
    assert vm.feed[0]["text"] == "我是好人"
