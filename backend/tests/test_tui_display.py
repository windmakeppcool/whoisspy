"""终端渲染测试：座次表、阶段指示、对话流。"""

import pytest
from app.tui.viewmodel import MatchVM
from app.tui.display import render_header, render_feed


def test_渲染头部_空状态():
    """验证空状态渲染。"""
    vm = MatchVM()
    output = render_header(vm, god_view=True)
    assert "等待开局" in output
    assert "上帝视角" in output


def test_渲染头部_有阶段():
    """验证有阶段时渲染。"""
    vm = MatchVM(day=2, phase="day", label="白天发言")
    output = render_header(vm, god_view=False)
    assert "第2天" in output
    assert "白天发言" in output
    assert "沉浸视角" in output


def test_渲染对话流_发言():
    """验证发言渲染。"""
    vm = MatchVM(feed=[
        {"type": "speech", "speaker": 1, "text": "你好"},
        {"type": "speech", "speaker": 2, "text": "我同意"},
    ])
    output = render_feed(vm)
    assert "1号" in output
    assert "你好" in output
    assert "2号" in output
    assert "我同意" in output


def test_渲染对话流_系统消息():
    """验证系统消息渲染。"""
    vm = MatchVM(feed=[
        {"type": "system", "text": "狼队选择击杀 3号"},
    ])
    output = render_feed(vm)
    assert "狼队选择击杀 3号" in output


def test_渲染对话流_投票分支():
    """验证 vote 类型走 [投票] 分支（此前零覆盖）。"""
    vm = MatchVM(feed=[
        {"type": "vote", "speaker": 1, "text": "1号 投票给 2号"},
        {"type": "vote", "speaker": 3, "text": "3号 弃票"},
    ])
    output = render_feed(vm)
    assert "[投票]" in output
    assert "1号 投票给 2号" in output
    assert "3号 弃票" in output


def test_渲染对话流_无发言人else分支():
    """验证非 system/vote 且无 speaker 时走裸文本 else 分支（此前零覆盖）。"""
    vm = MatchVM(feed=[
        {"type": "notice", "text": "无座位的提示消息"},
    ])
    output = render_feed(vm)
    assert "无座位的提示消息" in output
    assert "号:" not in output  # 不应渲染成 "{speaker}号: {text}"


def test_渲染对话流_空():
    """验证空对话流。"""
    vm = MatchVM(feed=[])
    output = render_feed(vm)
    assert "等待事件" in output


def test_座次表渲染输出_gbk可编码():
    """座次表在 GBK 代码页终端（中文 Windows 默认）必须可编码。

    此前用 ✓/✗（U+2713/U+2717），GBK 终端抛 UnicodeEncodeError 使渲染
    任务静默死亡、TUI 卡在初始画面（bug 回归）。
    """
    from app.tui.display import render_seats

    vm = MatchVM(seats=[
        {"seat": 1, "role": "villager", "alive": True},
        {"seat": 2, "role": "wolf", "alive": False},
    ])
    output = render_seats(vm, god_view=True)
    output.encode("gbk")  # 不可编码字符会在此抛 UnicodeEncodeError
    assert "座次表" in output
    assert "1" in output and "2" in output


def test_座次表存活与死亡状态可区分():
    from app.tui.display import render_seats

    vm = MatchVM(seats=[
        {"seat": 1, "role": "villager", "alive": True},
        {"seat": 2, "role": "wolf", "alive": False},
    ])
    output = render_seats(vm, god_view=True)
    lines = output
    # 存活与死亡的标记必须不同且都可 GBK 编码
    assert ("1" + ALIVE_MARK) in lines
    assert ("2" + DEAD_MARK) in lines


ALIVE_MARK = "生"
DEAD_MARK = "殁"
