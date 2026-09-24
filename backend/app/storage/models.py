"""SQLModel 表定义：match / match_seat / game_event / llm_call。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlmodel import Field, SQLModel, Text, UniqueConstraint


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
    # 创建时固化的人设与接入快照（D10/D11）：历史对局不依赖后续配置变更即可复现
    style: str = ""
    strategy: str = ""
    provider_id: str = ""
    base_url: str = ""
    api_key_env: str = ""  # 只存环境变量名，绝不存 key 本体
    model: str = ""
    price_per_mtok_in: float = 0.0
    price_per_mtok_out: float = 0.0
    price_per_mtok_cached_in: float = 0.0
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

    __table_args__ = (
        # 对局内 seq 唯一：跨进程/多实例写也不可能出现重复游标（引擎仍单写者）
        UniqueConstraint("match_id", "seq", name="uq_game_event_match_seq"),
        {"sqlite_autoincrement": True},
    )


class LlmCallRow(SQLModel, table=True):
    __tablename__ = "llm_call"

    id: int | None = Field(default=None, primary_key=True)
    match_id: int = Field(foreign_key="match.id", index=True)
    purpose: str = ""
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_prompt_tokens: int = 0  # 前缀缓存命中的 prompt tokens（各家端点命名不同，已归一）
    cost_micros: int = 0
    latency_ms: int = 0
    status: str = "ok"
    ref_event_seq: int | None = None
    created_at: datetime = Field(default_factory=_now)


def dumps(v: Any) -> str:
    return _dumps(v)


def loads(s: str) -> Any:
    return json.loads(s)
