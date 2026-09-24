"""Repository 抽象与 SQLite 实现。

Protocol 面向未来换 Postgres（D9）；SQLite 实现全参数化查询（安全规范）。
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Protocol

import aiosqlite  # noqa: F401  （SQLAlchemy 通过 URL 装载该驱动，此处保留显式依赖声明）
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import select

from app.core import Event, filtered_view
from app.storage.models import (
    GameEventRow,
    LlmCallRow,
    MatchRow,
    MatchSeatRow,
    dumps,
    loads,
)

log = logging.getLogger(__name__)


class MatchRepository(Protocol):
    async def init(self) -> None: ...
    async def close(self) -> None: ...
    async def create_match(self, *, game_type: str, ruleset: str, board: dict[str, Any],
                           rng_seed: int, seats: list[dict[str, Any]]) -> dict[str, Any]: ...
    async def get_match(self, match_id: int) -> dict[str, Any] | None: ...
    async def list_matches(self) -> list[dict[str, Any]]: ...
    async def update_match(self, match_id: int, *, status: str,
                           result: dict[str, Any] | None = None) -> None: ...
    async def set_seat_roles(self, match_id: int, roles: dict[int, str]) -> None: ...
    async def append_event(self, match_id: int, event: Event) -> Event: ...
    async def list_events(self, match_id: int, after_seq: int, view: str) -> list[Event]: ...


class UsageRepository(Protocol):
    async def init(self) -> None: ...
    async def close(self) -> None: ...
    async def record_call(self, *, match_id: int, purpose: str, model: str,
                          prompt_tokens: int, completion_tokens: int,
                          cost_micros: int, latency_ms: int, status: str,
                          cached_prompt_tokens: int = 0,
                          ref_event_seq: int | None = None) -> None: ...
    async def summarize(self, match_id: int) -> dict[str, Any]: ...


def _default_db_path() -> str:
    p = Path(__file__).resolve().parents[2] / "data" / "whoisspy.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return str(p)


def _match_dict(row: MatchRow, seats: list[MatchSeatRow]) -> dict[str, Any]:
    return {
        "id": row.id,
        "game_type": row.game_type,
        "ruleset": row.ruleset,
        "board": loads(row.board_json),
        "rng_seed": row.rng_seed,
        "status": row.status,
        "result": loads(row.result_json),
        "current_seq": row.current_seq,
        "created_at": row.created_at.isoformat(),
        "seats": [
            {
                "seat": s.seat, "name": s.name, "persona_id": s.persona_id,
                "style": s.style, "strategy": s.strategy,
                "provider_id": s.provider_id,
                "base_url": s.base_url, "api_key_env": s.api_key_env,
                "model": s.model, "role": s.role,
                "price_per_mtok_in": s.price_per_mtok_in,
                "price_per_mtok_out": s.price_per_mtok_out,
                "price_per_mtok_cached_in": s.price_per_mtok_cached_in,
            }
            for s in sorted(seats, key=lambda x: x.seat)
        ],
    }


class SqliteMatchRepository:
    """SQLite + aiosqlite 实现。单写者约定：append_event 由 MatchRunner 独占调用。

    seq 由**数据库原子自增**分配（UPDATE ... RETURNING），单进程内再叠一把 asyncio 锁：
    即使将来多进程/多实例共用同一个库，也不会分配出重复 seq（表上还有唯一约束兜底）。
    """

    # 旧库补列：固定 DDL（无外部输入），重复执行幂等；列已存在时吞掉 duplicate column
    _MIGRATE_COLUMNS: tuple[str, ...] = (
        "ALTER TABLE match_seat ADD COLUMN style TEXT DEFAULT ''",
        "ALTER TABLE match_seat ADD COLUMN strategy TEXT DEFAULT ''",
        "ALTER TABLE match_seat ADD COLUMN provider_id TEXT DEFAULT ''",
        "ALTER TABLE match_seat ADD COLUMN price_per_mtok_in REAL DEFAULT 0",
        "ALTER TABLE match_seat ADD COLUMN price_per_mtok_out REAL DEFAULT 0",
        "ALTER TABLE match_seat ADD COLUMN price_per_mtok_cached_in REAL DEFAULT 0",
    )
    # 关键约束：失败**不能静默**——若旧库已有重复 (match_id, seq)，
    # 索引建不上而没人知道，seq 唯一性从此名存实亡（见 duplicate_seq_groups）
    _MIGRATE_INDEXES: tuple[str, ...] = (
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_game_event_match_seq ON game_event(match_id, seq)",
    )

    def __init__(self, db_path: str | None = None):
        self._path = db_path or _default_db_path()
        self._engine = create_async_engine(f"sqlite+aiosqlite:///{self._path}")
        self._maker = async_sessionmaker(self._engine, expire_on_commit=False)
        self._seq_lock = asyncio.Lock()

    async def init(self) -> None:
        async with self._engine.begin() as conn:
            await conn.exec_driver_sql("PRAGMA journal_mode=WAL")
            await conn.exec_driver_sql("PRAGMA busy_timeout=5000")
            await conn.run_sync(SQLModel.metadata.create_all)
        for ddl in self._MIGRATE_COLUMNS:
            try:
                async with self._engine.begin() as conn:
                    await conn.exec_driver_sql(ddl)
            except Exception:  # 列已存在 → 幂等跳过
                pass
        for ddl in self._MIGRATE_INDEXES:
            try:
                async with self._engine.begin() as conn:
                    await conn.exec_driver_sql(ddl)
            except Exception as e:
                dups = await self.duplicate_seq_groups()
                log.error("补唯一索引失败（%s）；重复 (match_id, seq) 前几组: %s。"
                          "seq 唯一性当前不成立，请先清理重复事件再重启。", e, dups[:5])

    async def duplicate_seq_groups(self, limit: int = 20) -> list[tuple[int, int, int]]:
        """返回重复 (match_id, seq) 组 [(match_id, seq, 次数)]，用于启动自检与排障。"""
        async with self._session() as sess:
            rows = await sess.execute(text(
                "SELECT match_id, seq, COUNT(*) AS n FROM game_event "
                "GROUP BY match_id, seq HAVING COUNT(*) > 1 ORDER BY n DESC LIMIT :lim"),
                {"lim": limit})
            return [(int(r[0]), int(r[1]), int(r[2])) for r in rows.all()]

    async def close(self) -> None:
        await self._engine.dispose()

    def _session(self):
        return self._maker()

    async def create_match(self, *, game_type: str, ruleset: str, board: dict[str, Any],
                           rng_seed: int, seats: list[dict[str, Any]]) -> dict[str, Any]:
        row = MatchRow(game_type=game_type, ruleset=ruleset,
                       board_json=dumps(board), rng_seed=rng_seed, status="created")
        async with self._session() as sess:
            sess.add(row)
            await sess.commit()
            await sess.refresh(row)
            for s in seats:
                sess.add(MatchSeatRow(match_id=row.id, seat=s["seat"], name=s.get("name", ""),
                                      persona_id=s.get("persona_id", ""),
                                      style=s.get("style", ""),
                                      strategy=s.get("strategy", ""),
                                      provider_id=s.get("provider_id", ""),
                                      base_url=s.get("base_url", ""),
                                      api_key_env=s.get("api_key_env", ""),
                                      model=s.get("model", ""),
                                      price_per_mtok_in=float(s.get("price_per_mtok_in", 0.0) or 0.0),
                                      price_per_mtok_out=float(s.get("price_per_mtok_out", 0.0) or 0.0),
                                      price_per_mtok_cached_in=float(
                                          s.get("price_per_mtok_cached_in", 0.0) or 0.0),
                                      role=s.get("role", "")))
            await sess.commit()
            seat_rows = list((await sess.execute(select(MatchSeatRow).where(MatchSeatRow.match_id == row.id)) ).scalars())
            return _match_dict(row, seat_rows)

    async def get_match(self, match_id: int) -> dict[str, Any] | None:
        async with self._session() as sess:
            row = await sess.get(MatchRow, match_id)
            if row is None:
                return None
            seat_rows = list((await sess.execute(select(MatchSeatRow).where(MatchSeatRow.match_id == match_id))).scalars())
            return _match_dict(row, seat_rows)

    async def list_matches(self) -> list[dict[str, Any]]:
        async with self._session() as sess:
            rows = list((await sess.execute(select(MatchRow).order_by(MatchRow.id.desc()))).scalars())
            if not rows:
                return []
            ids = [row.id for row in rows]
            seat_rows = list((await sess.execute(
                select(MatchSeatRow).where(MatchSeatRow.match_id.in_(ids)))).scalars())
        grouped: dict[int, list[MatchSeatRow]] = {}
        for s in seat_rows:
            grouped.setdefault(s.match_id, []).append(s)
        return [_match_dict(row, grouped.get(row.id, [])) for row in rows]

    async def update_match(self, match_id: int, *, status: str,
                           result: dict[str, Any] | None = None) -> None:
        async with self._session() as sess:
            row = await sess.get(MatchRow, match_id)
            if row is None:
                raise ValueError(f"对局不存在: {match_id}")
            row.status = status
            if result is not None:
                row.result_json = dumps(result)
            await sess.commit()

    async def set_seat_roles(self, match_id: int, roles: dict[int, str]) -> None:
        async with self._session() as sess:
            seat_rows = list((await sess.execute(select(MatchSeatRow).where(MatchSeatRow.match_id == match_id))).scalars())
            for s in seat_rows:
                if s.seat in roles:
                    s.role = roles[s.seat]
            await sess.commit()

    async def append_event(self, match_id: int, event: Event) -> Event:
        """seq 由 DB 原子自增分配（UPDATE ... RETURNING），保证并发/多进程下唯一连续。"""
        async with self._seq_lock:
            async with self._session() as sess:
                row = await sess.get(MatchRow, match_id)
                if row is None:
                    raise ValueError(f"对局不存在: {match_id}")
                result = await sess.execute(
                    text("UPDATE match SET current_seq = current_seq + 1 "
                         "WHERE id = :mid RETURNING current_seq"),
                    {"mid": match_id})
                seq = int(result.scalar_one())
                sess.add(GameEventRow(
                    match_id=match_id, seq=seq, type=event.type,
                    day_index=event.day_index, phase=event.phase,
                    payload_json=dumps(event.payload),
                    vis_level=event.vis.level, vis_seats_json=dumps(event.vis.seats),
                ))
                await sess.commit()
        event.seq = seq
        return event

    async def list_events(self, match_id: int, after_seq: int, view: str) -> list[Event]:
        """读事件并做**出站可见性过滤**（core.filtered_view 是唯一过滤点）。"""
        async with self._session() as sess:
            rows = list((await sess.execute(select(GameEventRow)
                .where(GameEventRow.match_id == match_id, GameEventRow.seq > after_seq)
                .order_by(GameEventRow.seq))).scalars())
        out: list[Event] = []
        for r in rows:
            ev = Event(
                type=r.type, payload=loads(r.payload_json),
                day_index=r.day_index, phase=r.phase,
                vis=_vis_from(r.vis_level, loads(r.vis_seats_json)), seq=r.seq,
            )
            if filtered_view(ev, view) is not None:
                out.append(ev)
        return out


def _vis_from(level: str, seats: list[int]):
    from app.core import VisMeta

    return VisMeta(level=level, seats=seats)  # type: ignore[arg-type]


def _hit_rate(cached: int, prompt: int) -> float:
    """前缀缓存命中率 = 命中 tokens / 总 prompt tokens；无 prompt 时归 0（避免除零）。"""
    return cached / prompt if prompt else 0.0


class SqliteUsageRepository:
    """用量库。create_all 不会给已有表加列，_MIGRATE_COLUMNS 负责旧库补列（固定 DDL，无外部输入）。"""

    _MIGRATE_COLUMNS: tuple[str, ...] = (
        "ALTER TABLE llm_call ADD COLUMN cached_prompt_tokens INTEGER DEFAULT 0",
    )

    def __init__(self, db_path: str | None = None):
        self._path = db_path or _default_db_path()
        self._engine = create_async_engine(f"sqlite+aiosqlite:///{self._path}")
        self._maker = async_sessionmaker(self._engine, expire_on_commit=False)

    async def init(self) -> None:
        async with self._engine.begin() as conn:
            await conn.exec_driver_sql("PRAGMA journal_mode=WAL")
            await conn.exec_driver_sql("PRAGMA busy_timeout=5000")
            await conn.run_sync(SQLModel.metadata.create_all)
        # 补列逐条独立事务：列已存在时 SQLite 报 duplicate column，吞掉即幂等
        for ddl in self._MIGRATE_COLUMNS:
            try:
                async with self._engine.begin() as conn:
                    await conn.exec_driver_sql(ddl)
            except Exception:
                pass

    async def close(self) -> None:
        await self._engine.dispose()

    def _session(self):
        return self._maker()

    async def record_call(self, *, match_id: int, purpose: str, model: str,
                          prompt_tokens: int, completion_tokens: int,
                          cost_micros: int, latency_ms: int, status: str,
                          cached_prompt_tokens: int = 0,
                          ref_event_seq: int | None = None) -> None:
        async with self._session() as sess:
            sess.add(LlmCallRow(
                match_id=match_id, purpose=purpose, model=model,
                prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                cached_prompt_tokens=cached_prompt_tokens,
                cost_micros=cost_micros, latency_ms=latency_ms, status=status,
                ref_event_seq=ref_event_seq,
            ))
            await sess.commit()

    async def summarize(self, match_id: int) -> dict[str, Any]:
        async with self._session() as sess:
            rows = list((await sess.execute(select(LlmCallRow).where(LlmCallRow.match_id == match_id))).scalars())
        by_model: dict[str, dict[str, Any]] = {}
        total = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
                 "cached_prompt_tokens": 0, "cost_micros": 0}
        for r in rows:
            total["calls"] += 1
            total["prompt_tokens"] += r.prompt_tokens
            total["completion_tokens"] += r.completion_tokens
            total["cached_prompt_tokens"] += r.cached_prompt_tokens
            total["cost_micros"] += r.cost_micros
            m = by_model.setdefault(r.model, {"calls": 0, "prompt_tokens": 0,
                                              "completion_tokens": 0,
                                              "cached_prompt_tokens": 0, "cost_micros": 0})
            m["calls"] += 1
            m["prompt_tokens"] += r.prompt_tokens
            m["completion_tokens"] += r.completion_tokens
            m["cached_prompt_tokens"] += r.cached_prompt_tokens
            m["cost_micros"] += r.cost_micros
        for m in by_model.values():
            m["cache_hit_rate"] = _hit_rate(m["cached_prompt_tokens"], m["prompt_tokens"])
        return {
            "total_calls": total["calls"],
            "prompt_tokens": total["prompt_tokens"],
            "completion_tokens": total["completion_tokens"],
            "cached_prompt_tokens": total["cached_prompt_tokens"],
            "cache_hit_rate": _hit_rate(total["cached_prompt_tokens"], total["prompt_tokens"]),
            "cost_micros": total["cost_micros"],
            "by_model": by_model,
        }
