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


def test_默认match_id为0表示自动开局():
    """验证 --match-id 默认 0：TUI 启动时自动创建一局。"""
    args = parse_args(["--tui"])
    assert args.match_id == 0


def test_解析real参数():
    """验证 --real 开关：TUI 自动开局用真实 LLM。"""
    args = parse_args(["--tui", "--real"])
    assert args.real is True


def test_默认不启用real():
    args = parse_args(["--tui"])
    assert args.real is False


def test_real自动开局载荷为真实provider(monkeypatch):
    """--real 时 create_match_via_api 用首个非 mock provider 的 base_url/model。"""
    import asyncio
    import json
    import tempfile
    from pathlib import Path
    from unittest.mock import MagicMock, patch, AsyncMock
    from app.main import create_match_via_api

    monkeypatch.setenv("MIMO_API_KEY", "tp-test")
    tmp = Path(tempfile.mkdtemp())
    (tmp / "providers.json").write_text(json.dumps({"providers": [
        {"id": "mimo", "base_url": "https://x.example/v1", "api_key_env": "MIMO_API_KEY",
         "currency": "CNY", "models": [{"id": "mimo-flash"}]},
        {"id": "mock", "base_url": "", "api_key_env": "", "currency": "CNY",
         "models": [{"id": "mock"}]}]}), encoding="utf-8")

    fake_resp = MagicMock()
    fake_resp.json.return_value = {"id": 9, "status": "running"}
    fake_resp.raise_for_status.return_value = None
    fake_client = MagicMock()
    fake_client.post = AsyncMock(return_value=fake_resp)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=fake_client):
        mid = asyncio.run(create_match_via_api("http://127.0.0.1:8000", real=True,
                                               data_dir=str(tmp)))

    assert mid == 9
    body = fake_client.post.call_args.kwargs["json"]
    assert len(body["seats"]) == 6
    assert all(s["model"] == "mimo-flash" for s in body["seats"])
    assert all(s["base_url"] == "https://x.example/v1" for s in body["seats"])
    assert all(s["api_key_env"] == "MIMO_API_KEY" for s in body["seats"])


def test_自动开局请求载荷为6座mock局():
    """create_match_via_api 需 POST 一局 6 座位全 mock 的 p6-classic。"""
    from unittest.mock import MagicMock, patch, AsyncMock
    from app.main import create_match_via_api

    fake_resp = MagicMock()
    fake_resp.json.return_value = {"id": 7, "status": "running"}
    fake_resp.raise_for_status.return_value = None

    fake_client = MagicMock()
    fake_client.post = AsyncMock(return_value=fake_resp)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)

    import asyncio
    with patch("httpx.AsyncClient", return_value=fake_client):
        mid = asyncio.run(create_match_via_api("http://127.0.0.1:8000"))

    assert mid == 7
    args, kwargs = fake_client.post.call_args
    assert args[0] == "http://127.0.0.1:8000/api/matches"
    body = kwargs["json"]
    assert body["board"]["id"] == "p6-classic"
    assert len(body["seats"]) == 6
    assert all(s["model"] == "mock" for s in body["seats"])
    assert [s["seat"] for s in body["seats"]] == [1, 2, 3, 4, 5, 6]
