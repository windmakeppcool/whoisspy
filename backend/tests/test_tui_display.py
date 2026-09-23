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


def test_渲染对话流_空():
    """验证空对话流。"""
    vm = MatchVM(feed=[])
    output = render_feed(vm)
    assert "等待事件" in output
