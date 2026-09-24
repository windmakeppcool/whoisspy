"""导出整局发言 JSON：默认最近一局，或 --match-id 指定。

用法：
    python scripts/export_dialog.py                    # 导出最近一局 → match-<id>-dialog.json
    python scripts/export_dialog.py --match-id 13      # 指定对局
    python scripts/export_dialog.py --match-id 13 --out out.json   # 指定输出文件
    python scripts/export_dialog.py --db data/other.db # 指定数据库（默认 backend/data/whoisspy.db）

直连 SQLite，无需后端服务在跑；内容为上帝视角分段对话（含狼队密聊/独白/夜晚操作）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.export.dialog import render_dialog  # noqa: E402
from app.storage.repo import SqliteMatchRepository  # noqa: E402


async def export_dialog(db_path: str | None = None, match_id: int | None = None,
                        out: str | Path | None = None) -> Path:
    """导出对局发言 JSON 到文件。match_id 缺省取最近一局（id 最大）。"""
    repo = SqliteMatchRepository(db_path)
    await repo.init()
    try:
        if match_id is None:
            matches = await repo.list_matches()  # 按 id 倒序，首条即最近一局
            if not matches:
                raise ValueError("数据库中没有对局记录")
            match_id = matches[0]["id"]
        m = await repo.get_match(match_id)
        if m is None:
            raise ValueError(f"对局不存在: {match_id}")
        events = await repo.list_events(match_id, after_seq=0, view="god")
        data = render_dialog(match_id=match_id, game_type=m["game_type"], events=events)
        out_path = Path(out) if out else Path.cwd() / f"match-{match_id}-dialog.json"
        out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        return out_path
    finally:
        await repo.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="导出整局发言 JSON（默认最近一局）")
    ap.add_argument("--match-id", type=int, default=None, help="对局 ID（缺省取最近一局）")
    ap.add_argument("--db", default=None, help="数据库路径（默认 backend/data/whoisspy.db）")
    ap.add_argument("--out", default=None, help="输出文件路径（默认 match-<id>-dialog.json）")
    args = ap.parse_args()

    async def _run() -> int:
        out_path = await export_dialog(db_path=args.db, match_id=args.match_id,
                                       out=args.out)
        print(f"已导出: {out_path}")
        return 0

    try:
        return asyncio.run(_run())
    except ValueError as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())