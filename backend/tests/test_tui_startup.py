"""启动参数测试。"""

import pytest
from unittest.mock import patch, AsyncMock
from app.main import parse_args


def test_解析tui参数():
    """验证 --tui 参数解析。"""
    args = parse_args(["--tui"])
    assert args.tui == True


def test_默认不启用tui():
    """验证默认不启用 TUI。"""
    args = parse_args([])
    assert args.tui == False


def test_解析match_id参数():
    """验证 --match-id 参数解析。"""
    args = parse_args(["--tui", "--match-id", "42"])
    assert args.tui == True
    assert args.match_id == 42
