"""Repository 抽象与 SQLite 实现。

Protocol 面向未来换 Postgres（D9）；SQLite 实现全参数化查询（安全规范）。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Protocol

import aiosqlite
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import select

from app.core import Event
from app.storage.models import (
    GameEventRow,
    LlmCallRow,
    MatchRow,
    MatchSeatRow,
    dumps,
    loads,
)


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
                "base_url": s.base_url, "api_key_env": s.api_key_env,
                "model": s.model, "role": s.role,
            }
            for s in sorted(seats, key=lambda x: x.seat)
        ],
    }


class SqliteMatchRepository:
    """SQLite + aiosqlite 实现。单写者约定：append_event 由 MatchRunner 独占调用。

    append_event 内部用 asyncio 锁串行化 seq 分配（ballot/收刀的并行 gather 共享同一 repo）。
    """

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
                                      base_url=s.get("base_url", ""),
                                      api_key_env=s.get("api_key_env", ""),
                                      model=s.get("model", ""), role=s.get("role", "")))
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
            out: list[dict[str, Any]] = []
            for row in rows:
                seat_rows = list((await sess.execute(select(MatchSeatRow).where(MatchSeatRow.match_id == row.id))).scalars())
                out.append(_match_dict(row, seat_rows))
            return out

    async def update_match(self, match_id: int, *, status: str,
                           result: dict[str, Any] | None = None) -> None:
        async with self._session() as sess:
            row = await sess.get(MatchRow, match_id)
            assert row is not None
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
        """seq 取自 match.current_seq+1，锁内读改写，保证并行 gather 下连续唯一。"""
        import asyncio as _asyncio

        async with self._seq_lock:
            async with self._session() as sess:
                row = await sess.get(MatchRow, match_id)
                assert row is not None
                seq = row.current_seq + 1
                row.current_seq = seq
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
            if view == "god" or ev.vis.level == "public":
                out.append(ev)
        return out


def _vis_from(level: str, seats: list[int]):
    from app.core import VisMeta

    return VisMeta(level=level, seats=seats)  # type: ignore[arg-type]


class SqliteUsageRepository:
    def __init__(self, db_path: str | None = None):
        self._path = db_path or _default_db_path()
        self._engine = create_async_engine(f"sqlite+aiosqlite:///{self._path}")
        self._maker = async_sessionmaker(self._engine, expire_on_commit=False)

    async def init(self) -> None:
        async with self._engine.begin() as conn:
            await conn.exec_driver_sql("PRAGMA journal_mode=WAL")
            await conn.exec_driver_sql("PRAGMA busy_timeout=5000")
            await conn.run_sync(SQLModel.metadata.create_all)

    async def close(self) -> None:
        await self._engine.dispose()

    def _session(self):
        return self._maker()

    async def record_call(self, *, match_id: int, purpose: str, model: str,
                          prompt_tokens: int, completion_tokens: int,
                          cost_micros: int, latency_ms: int, status: str,
                          ref_event_seq: int | None = None) -> None:
        async with self._session() as sess:
            sess.add(LlmCallRow(
                match_id=match_id, purpose=purpose, model=model,
                prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                cost_micros=cost_micros, latency_ms=latency_ms, status=status,
                ref_event_seq=ref_event_seq,
            ))
            await sess.commit()

    async def summarize(self, match_id: int) -> dict[str, Any]:
        async with self._session() as sess:
            rows = list((await sess.execute(select(LlmCallRow).where(LlmCallRow.match_id == match_id))).scalars())
        by_model: dict[str, dict[str, int]] = {}
        total = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_micros": 0}
        for r in rows:
            total["calls"] += 1
            total["prompt_tokens"] += r.prompt_tokens
            total["completion_tokens"] += r.completion_tokens
            total["cost_micros"] += r.cost_micros
            m = by_model.setdefault(r.model, {"calls": 0, "prompt_tokens": 0,
                                              "completion_tokens": 0, "cost_micros": 0})
            m["calls"] += 1
            m["prompt_tokens"] += r.prompt_tokens
            m["completion_tokens"] += r.completion_tokens
            m["cost_micros"] += r.cost_micros
        return {
            "total_calls": total["calls"],
            "prompt_tokens": total["prompt_tokens"],
            "completion_tokens": total["completion_tokens"],
            "cost_micros": total["cost_micros"],
            "by_model": by_model,
        }
