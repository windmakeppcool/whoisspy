"""导出脚本测试（Red 先行）：scripts/export_dialog.py 指定/最近一局导出。"""

import asyncio
import json
import sys
from pathlib import Path

import pytest

from app.storage.repo import SqliteMatchRepository

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from export_dialog import export_dialog  # noqa: E402

SEATS = [{"seat": i, "name": f"p{i}", "persona_id": "calm", "base_url": "",
          "api_key_env": "", "model": "mock", "role": ""} for i in range(1, 7)]


async def _create_match(repo, board: str = "p6-classic") -> int:
    m = await repo.create_match(game_type="werewolf", ruleset="minimal",
                                board={"id": board}, rng_seed=1, seats=SEATS)
    return m["id"]


class TestExportDialogScript:
    async def test_指定match_id导出(self, tmp_path):
        repo = SqliteMatchRepository(db_path=str(tmp_path / "t.db"))
        await repo.init()
        try:
            mid = await _create_match(repo)
        finally:
            await repo.close()
        out = await export_dialog(db_path=str(tmp_path / "t.db"), match_id=mid,
                                  out=tmp_path / "dialog.json")
        assert out.exists() and out.name == "dialog.json"
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["match_id"] == mid
        assert data["game_type"] == "werewolf"
        assert "exported_at" in data and "segments" in data

    async def test_缺省输出文件名含match_id(self, tmp_path, monkeypatch):
        repo = SqliteMatchRepository(db_path=str(tmp_path / "t.db"))
        await repo.init()
        try:
            mid = await _create_match(repo)
        finally:
            await repo.close()
        monkeypatch.chdir(tmp_path)
        out = await export_dialog(db_path=str(tmp_path / "t.db"), match_id=mid)
        assert out.exists() and out.name == f"match-{mid}-dialog.json"

    async def test_默认导出最近一局(self, tmp_path):
        repo = SqliteMatchRepository(db_path=str(tmp_path / "t.db"))
        await repo.init()
        try:
            old = await _create_match(repo)
            new = await _create_match(repo)  # id 递增，new > old
        finally:
            await repo.close()
        out = await export_dialog(db_path=str(tmp_path / "t.db"),
                                  out=tmp_path / "latest.json")
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["match_id"] == new
        assert data["match_id"] > old

    async def test_指定不存在对局报错(self, tmp_path):
        with pytest.raises(ValueError, match="不存在"):
            await export_dialog(db_path=str(tmp_path / "t.db"), match_id=999)

    async def test_空库报错(self, tmp_path):
        repo = SqliteMatchRepository(db_path=str(tmp_path / "t.db"))
        await repo.init()
        await repo.close()
        with pytest.raises(ValueError, match="没有对局"):
            await export_dialog(db_path=str(tmp_path / "t.db"))