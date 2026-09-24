"""配置加载器测试（Red 先行）：providers/personas/boards JSON 加载、回落、坏配置拒绝、
.env 解析与 api key 解析（key 不落库只经环境变量）。"""

import os
from pathlib import Path

import pytest

from app.config.loader import (
    ConfigBundle,
    apply_boards,
    load_config,
    parse_env_file,
    resolve_api_key,
)

PROVIDERS_JSON = """{
  "providers": [
    {
      "id": "mimo",
      "base_url": "https://token-plan-cn.xiaomimimo.com/v1",
      "api_key_env": "MIMO_API_KEY",
      "currency": "CNY",
      "models": [
        {"id": "mimo-v2.6-flash", "price_per_mtok_in": 1.0, "price_per_mtok_out": 3.0}
      ]
    },
    {"id": "mock", "base_url": "", "api_key_env": "", "currency": "CNY",
     "models": [{"id": "mock", "price_per_mtok_in": 0, "price_per_mtok_out": 0}]}
  ]
}
"""

PERSONAS_JSON = """{
  "personas": [
    {"id": "direct", "name": "直球选手", "style": "简短直接。", "strategy": "有怀疑直说。"}
  ]
}
"""

BOARDS_JSON = """{
  "boards": [
    {"id": "p6-classic", "game_type": "werewolf", "ruleset": "minimal",
     "roles": {"wolf": 2, "seer": 1, "villager": 3},
     "wolf_meeting_rounds": 2, "max_days": 8}
  ]
}
"""


@pytest.fixture()
def data_dir(tmp_path: Path) -> Path:
    return tmp_path


class TestLoadConfig:
    async def test_三个文件齐全_按文件加载(self, data_dir: Path):
        (data_dir / "providers.json").write_text(PROVIDERS_JSON, encoding="utf-8")
        (data_dir / "personas.json").write_text(PERSONAS_JSON, encoding="utf-8")
        (data_dir / "boards.json").write_text(BOARDS_JSON, encoding="utf-8")
        bundle = load_config(data_dir)
        assert isinstance(bundle, ConfigBundle)
        assert [p["id"] for p in bundle.providers] == ["mimo", "mock"]
        assert bundle.personas[0]["id"] == "direct"
        assert bundle.boards["p6-classic"]["roles"]["wolf"] == 2

    async def test_缺文件_回落内置默认(self, data_dir: Path):
        bundle = load_config(data_dir)  # 空目录
        assert any(p["id"] == "mock" for p in bundle.providers)  # 内置 DEFAULT_PROVIDERS
        assert len(bundle.personas) >= 6  # 内置 DEFAULT_PERSONAS
        assert "p6-classic" in bundle.boards  # 内置 PRESETS

    async def test_坏JSON_拒绝启动(self, data_dir: Path):
        (data_dir / "providers.json").write_text("{broken", encoding="utf-8")
        with pytest.raises(ValueError, match="providers.json"):
            load_config(data_dir)

    async def test_schema非法_拒绝启动(self, data_dir: Path):
        (data_dir / "personas.json").write_text('{"personas": [{"id": 1}]}', encoding="utf-8")
        with pytest.raises(ValueError, match="personas.json"):
            load_config(data_dir)


class TestApplyBoards:
    async def test_boards覆盖预设(self, data_dir: Path):
        (data_dir / "boards.json").write_text(BOARDS_JSON, encoding="utf-8")
        apply_boards(load_config(data_dir))
        try:
            from app.games.registry import PRESETS, resolve_board

            assert set(PRESETS) == {"p6-classic"}
            game, spec = resolve_board({"id": "p6-classic"})
            assert spec.player_count == 6
        finally:
            from app.config.loader import apply_default_boards

            apply_default_boards()


class TestParseEnvFile:
    async def test_解析KEY_VALUE与注释(self, tmp_path: Path):
        f = tmp_path / ".env"
        f.write_text(
            "# 注释\nBASE_URL=https://example.com/v1\nAPI_KEY=tp-abc123\n"
            "\nMODEL=mimo-v2.6-flash\nQUOTED=\"hello world\"\n",
            encoding="utf-8")
        env = parse_env_file(f)
        assert env == {"BASE_URL": "https://example.com/v1", "API_KEY": "tp-abc123",
                       "MODEL": "mimo-v2.6-flash", "QUOTED": "hello world"}

    async def test_文件不存在_返回空(self, tmp_path: Path):
        assert parse_env_file(tmp_path / "nope.env") == {}


class TestResolveApiKey:
    async def test_环境变量存在_返回key(self, monkeypatch):
        monkeypatch.setenv("MIMO_API_KEY", "tp-secret")
        assert resolve_api_key("MIMO_API_KEY") == "tp-secret"

    async def test_变量名为空_返回空串(self):
        assert resolve_api_key("") == ""

    async def test_变量缺失_返回空串不抛(self, monkeypatch):
        monkeypatch.delenv("NOT_EXIST_KEY", raising=False)
        assert resolve_api_key("NOT_EXIST_KEY") == ""


class TestLoadEnvIntoOsEnviron:
    async def test_加载env文件到环境(self, tmp_path: Path, monkeypatch):
        monkeypatch.delenv("API_KEY", raising=False)
        f = tmp_path / ".env"
        f.write_text("API_KEY=tp-abc\n", encoding="utf-8")
        from app.config.loader import load_env_file

        load_env_file(f)
        assert os.environ["API_KEY"] == "tp-abc"
        monkeypatch.delenv("API_KEY", raising=False)
