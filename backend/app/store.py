"""SQLite 存储层（docs/backend/10-storage.md，裸 aiosqlite）。

单进程单写者：seq 由调用方（flow emit）分配，UNIQUE(match_id, seq) 作不变量兜底。
存储层无游戏语义；表结构见 10-storage.md。
"""

from __future__ import annotations

import json
from typing import Any

import aiosqlite

from app.events import Event, Vis

_DDL = [
    """CREATE TABLE IF NOT EXISTS match (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        seed INTEGER NOT NULL,
        board_json TEXT NOT NULL,
        status TEXT NOT NULL,
        result_json TEXT,
        current_seq INTEGER NOT NULL DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS match_seat (
        match_id INTEGER NOT NULL, seat INTEGER NOT NULL,
        persona_id TEXT NOT NULL, style TEXT NOT NULL, strategy TEXT NOT NULL,
        provider_id TEXT NOT NULL, base_url TEXT NOT NULL, api_key_env TEXT NOT NULL,
        model TEXT NOT NULL,
        price_per_mtok_in REAL NOT NULL DEFAULT 0,
        price_per_mtok_out REAL NOT NULL DEFAULT 0,
        price_per_mtok_cached_in REAL,
        role TEXT,
        PRIMARY KEY (match_id, seat)
    )""",
    """CREATE TABLE IF NOT EXISTS game_event (
        match_id INTEGER NOT NULL, seq INTEGER NOT NULL,
        type TEXT NOT NULL, day_index INTEGER NOT NULL, phase TEXT NOT NULL,
        payload_json TEXT NOT NULL, vis_level TEXT NOT NULL, vis_seats_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (match_id, seq)
    )""",
    """CREATE TABLE IF NOT EXISTS llm_call (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id INTEGER NOT NULL, seat INTEGER NOT NULL, purpose TEXT NOT NULL,
        model TEXT NOT NULL,
        prompt_tokens INTEGER NOT NULL DEFAULT 0,
        completion_tokens INTEGER NOT NULL DEFAULT 0,
        cached_prompt_tokens INTEGER NOT NULL DEFAULT 0,
        cost_micros INTEGER NOT NULL DEFAULT 0,
        latency_ms INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""",
]


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


class Store:
    """对局存储（aiosqlite 连接封装；函数集对应 10-storage.md 二）。"""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    @classmethod
    async def init(cls, db_path: str) -> "Store":
        """建库建表（幂等），返回连接。

        旧版（SQLModel 时代）数据库不迁移：检测到 match 表缺 seed 列时
        抛清晰错误，提示删除旧库后重跑（14-migration 一）。
        """
        conn = await aiosqlite.connect(db_path)
        for ddl in _DDL:
            await conn.execute(ddl)
        await conn.commit()
        await cls._check_schema(conn)
        return cls(conn)

    @staticmethod
    async def _check_schema(conn: aiosqlite.Connection) -> None:
        """旧库防御：match 表必须含 seed 列（旧 schema 缺失会报难以理解的错误）。"""
        cur = await conn.execute("PRAGMA table_info(match)")
        rows = await cur.fetchall()
        cols = {r[1] for r in rows}
        if "seed" not in cols:
            raise ValueError(
                "检测到旧版（SQLModel 时代）whoisspy.db：表结构不兼容且不迁移。"
                "请删除该数据库文件后重跑（或改名留档，见 docs/backend/14-migration.md）。")

    async def close(self) -> None:
        await self._conn.close()

    # ---------- 写入 ----------

    async def create_match(self, *, seed: int, board: dict[str, Any],
                           seats: list[dict[str, Any]]) -> int:
        """落 match + match_seat 快照（不包含 key 本体），返回 match_id。"""
        cur = await self._conn.execute(
            "INSERT INTO match (created_at, seed, board_json, status) VALUES (?,?,?,?)",
            (_now(), seed, json.dumps(board, ensure_ascii=False), "running"))
        mid = cur.lastrowid
        for s in seats:
            await self._conn.execute(
                """INSERT INTO match_seat (match_id, seat, persona_id, style, strategy,
                   provider_id, base_url, api_key_env, model,
                   price_per_mtok_in, price_per_mtok_out, price_per_mtok_cached_in)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (mid, s["seat"], s.get("persona_id", ""), s.get("style", ""),
                 s.get("strategy", ""), s.get("provider_id", ""),
                 s.get("base_url", ""), s.get("api_key_env", ""), s.get("model", ""),
                 s.get("price_per_mtok_in", 0.0), s.get("price_per_mtok_out", 0.0),
                 s.get("price_per_mtok_cached_in")))
        await self._conn.commit()
        return int(mid)

    async def append_event(self, match_id: int, event: Event) -> None:
        """追加一条事件（seq 由调用方分配好；UNIQUE 冲突 = 流程 bug 直接暴露）。"""
        await self._conn.execute(
            """INSERT INTO game_event (match_id, seq, type, day_index, phase,
               payload_json, vis_level, vis_seats_json, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (match_id, event.seq, event.type, event.day_index, event.phase,
             json.dumps(event.payload, ensure_ascii=False), event.vis.level,
             json.dumps(event.vis.seats), _now()))
        await self._conn.commit()

    async def add_llm_call(self, *, match_id: int, seat: int, purpose: str,
                           model: str, prompt_tokens: int, completion_tokens: int,
                           cached_prompt_tokens: int, cost_micros: int,
                           latency_ms: int, status: str) -> None:
        await self._conn.execute(
            """INSERT INTO llm_call (match_id, seat, purpose, model,
               prompt_tokens, completion_tokens, cached_prompt_tokens,
               cost_micros, latency_ms, status, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (match_id, seat, purpose, model, prompt_tokens, completion_tokens,
             cached_prompt_tokens, cost_micros, latency_ms, status, _now()))
        await self._conn.commit()

    async def set_seat_roles(self, match_id: int, roles: dict[int, str]) -> None:
        for seat_no, role in roles.items():
            await self._conn.execute(
                "UPDATE match_seat SET role=? WHERE match_id=? AND seat=?",
                (role, match_id, seat_no))
        await self._conn.commit()

    async def finalize_match(self, match_id: int, status: str,
                             result: dict[str, Any] | None) -> None:
        await self._conn.execute(
            "UPDATE match SET status=?, result_json=? WHERE id=?",
            (status, json.dumps(result, ensure_ascii=False) if result else None,
             match_id))
        await self._conn.commit()

    # ---------- 读取 ----------

    async def load_events(self, match_id: int) -> list[Event]:
        """按 seq 升序读全量事件（导出/折叠复算用）。"""
        cur = await self._conn.execute(
            "SELECT seq, type, day_index, phase, payload_json, vis_level, vis_seats_json "
            "FROM game_event WHERE match_id=? ORDER BY seq", (match_id,))
        rows = await cur.fetchall()
        events: list[Event] = []
        for row in rows:
            events.append(Event(
                seq=int(row[0]), type=row[1], day_index=int(row[2]), phase=row[3],
                payload=json.loads(row[4]),
                vis=Vis(level=row[5], seats=json.loads(row[6] or "[]"))))
        return events

    async def load_match(self, match_id: int) -> dict[str, Any] | None:
        cur = await self._conn.execute(
            "SELECT id, seed, board_json, status, result_json FROM match WHERE id=?",
            (match_id,))
        row = await cur.fetchone()
        if row is None:
            return None
        return {"id": int(row[0]), "seed": int(row[1]),
                "board": json.loads(row[2]), "status": row[3],
                "result": json.loads(row[4]) if row[4] else None}

    async def load_seats(self, match_id: int) -> list[dict[str, Any]]:
        cur = await self._conn.execute(
            "SELECT seat, persona_id, style, strategy, provider_id, base_url, "
            "api_key_env, model, price_per_mtok_in, price_per_mtok_out, "
            "price_per_mtok_cached_in, role FROM match_seat "
            "WHERE match_id=? ORDER BY seat", (match_id,))
        rows = await cur.fetchall()
        cols = ["seat", "persona_id", "style", "strategy", "provider_id", "base_url",
                "api_key_env", "model", "price_per_mtok_in", "price_per_mtok_out",
                "price_per_mtok_cached_in", "role"]
        return [dict(zip(cols, row)) for row in rows]

    async def usage_summary(self, match_id: int) -> dict[str, Any]:
        """汇总 calls/tokens/cost（含缓存命中率）；无调用时命中率 0（不除零）。"""
        cur = await self._conn.execute(
            """SELECT COUNT(*), COALESCE(SUM(prompt_tokens),0),
                      COALESCE(SUM(completion_tokens),0),
                      COALESCE(SUM(cached_prompt_tokens),0),
                      COALESCE(SUM(cost_micros),0)
               FROM llm_call WHERE match_id=?""", (match_id,))
        row = await cur.fetchone()
        calls, prompt, completion, cached, cost = (int(v) for v in row)
        return {
            "calls": calls,
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "cached_prompt_tokens": cached,
            "cost_micros": cost,
            "cache_hit_rate": cached / prompt if prompt else 0.0,
        }