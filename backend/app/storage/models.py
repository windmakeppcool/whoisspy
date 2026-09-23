"""SQLModel 表定义：match / match_seat / game_event / llm_call。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlmodel import Column, Field, SQLModel, Text


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _dumps(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False)


class MatchRow(SQLModel, table=True):
    __tablename__ = "match"

    id: int | None = Field(default=None, primary_key=True)
    game_type: str = Field(index=True)
    ruleset: str = ""
    board_json: str = Field(default="{}", sa_type=Text)
    rng_seed: int = 0
    status: str = Field(default="created", index=True)  # created/running/finished/stopped
    result_json: str = Field(default="null", sa_type=Text)
    current_seq: int = 0
    created_at: datetime = Field(default_factory=_now)


class MatchSeatRow(SQLModel, table=True):
    __tablename__ = "match_seat"

    id: int | None = Field(default=None, primary_key=True)
    match_id: int = Field(foreign_key="match.id", index=True)
    seat: int
    name: str = ""
    persona_id: str = ""
    base_url: str = ""
    api_key_env: str = ""
    model: str = ""
    role: str = ""  # 发牌后回填


class GameEventRow(SQLModel, table=True):
    __tablename__ = "game_event"

    id: int | None = Field(default=None, primary_key=True)
    match_id: int = Field(foreign_key="match.id", index=True)
    seq: int = Field(index=True)
    type: str
    day_index: int = 0
    phase: str = ""
    payload_json: str = Field(default="{}", sa_type=Text)
    vis_level: str = "public"
    vis_seats_json: str = Field(default="[]", sa_type=Text)

    __table_args__ = ({"sqlite_autoincrement": True},)


class LlmCallRow(SQLModel, table=True):
    __tablename__ = "llm_call"

    id: int | None = Field(default=None, primary_key=True)
    match_id: int = Field(foreign_key="match.id", index=True)
    purpose: str = ""
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_micros: int = 0
    latency_ms: int = 0
    status: str = "ok"
    ref_event_seq: int | None = None
    created_at: datetime = Field(default_factory=_now)


def dumps(v: Any) -> str:
    return _dumps(v)


def loads(s: str) -> Any:
    return json.loads(s)
