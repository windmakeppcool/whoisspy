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
