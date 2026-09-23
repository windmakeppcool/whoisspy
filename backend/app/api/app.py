"""FastAPI 应用工厂：matches / events / stream(SSE) / stop / usage / catalog。

可见性过滤复用 core.filtered_view 语义（服务端出站统一过滤，支柱 3）。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.config.defaults import DEFAULT_PERSONAS, DEFAULT_PROVIDERS
from app.engine.runner import MatchRunner
from app.games.registry import PRESETS, resolve_board
from app.llm.gateway import OpenAICompatGateway
from app.storage.repo import SqliteMatchRepository, SqliteUsageRepository


class SeatIn(BaseModel):
    seat: int
    persona_id: str = "calm-analyst"
    name: str = ""
    base_url: str = ""
    api_key_env: str = ""
    model: str = "mock"


class CreateMatchIn(BaseModel):
    game_type: str = "werewolf"
    board: dict[str, Any] = Field(default_factory=lambda: {"id": "p6-classic"})
    seats: list[SeatIn]


def create_app(db_path: str | None = None) -> FastAPI:
    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        await match_repo.init()
        await usage_repo.init()
        yield
        await match_repo.close()
        await usage_repo.close()

    app = FastAPI(title="whoisspy backend", lifespan=_lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=["*"],
                       allow_methods=["*"], allow_headers=["*"])
    match_repo = SqliteMatchRepository(db_path)
    usage_repo = SqliteUsageRepository(db_path)
    runners: dict[int, MatchRunner] = {}
    stop_flags: dict[int, asyncio.Event] = {}

    def _persona(persona_id: str) -> dict[str, str]:
        for p in DEFAULT_PERSONAS:
            if p["id"] == persona_id:
                return p
        return DEFAULT_PERSONAS[0]

    @app.post("/api/matches")
    async def create_match(body: CreateMatchIn) -> dict[str, Any]:
        try:
            game, spec = resolve_board(body.board)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        if not (spec.player_count == len(body.seats)):
            raise HTTPException(status_code=422,
                                detail=f"板子需要 {spec.player} 人，收到 {len(body.seats)} 个座位"
                                if False else f"板子需要 {spec.player_count} 人，收到 {len(body.seats)} 个座位")
        import random

        seed = random.randrange(1, 2**31)
        seats = [{
            "seat": s.seat, "name": s.name or _persona(s.persona_id)["name"],
            "persona_id": s.persona_id, "base_url": s.base_url,
            "api_key_env": s.api_key_env, "model": s.model, "role": "",
        } for s in sorted(body.seats, key=lambda x: x.seat)]
        m = await match_repo.create_match(
            game_type=body.game_type, ruleset=spec.ruleset,
            board={"id": body.board.get("id"), "ruleset": spec.ruleset,
                   "roles": spec.roles, "wolf_meeting_rounds": spec.wolf_meeting_rounds,
                   "max_days": spec.max_days},
            rng_seed=seed, seats=seats)
        _spawn_runner(m["id"], game, spec, seed, seats)
        return m

    def _spawn_runner(match_id: int, game, spec, seed: int, seats: list[dict]) -> None:
        seat_meta = {s["seat"]: {"model": s["model"], "base_url": s["base_url"],
                                 "api_key_env": s["api_key_env"],
                                 "style": _persona(s["persona_id"])["style"],
                                 "strategy": _persona(s["persona_id"])["strategy"],
                                 "role": ""}
                     for s in seats}
        stop = asyncio.Event()
        stop_flags[match_id] = stop

        class _Sink:
            async def record_call(self, **kw: Any) -> None:
                await usage_repo.record_call(match_id=match_id, **{
                    k: v for k, v in kw.items() if k != "match_id"})

        # 全部座位 model=mock → 启发式假 LLM（零网络、有内容）；否则真实 OpenAI 兼容网关
        if all(s["model"] == "mock" for s in seats):
            from app.llm.gateway import MockLLM

            gw = MockLLM(script=[], rng_seed=seed, usage_sink=_Sink())
        else:
            gw = OpenAICompatGateway(usage_sink=_Sink())
        runner = MatchRunner(match_id=match_id, game=game, spec=spec,
                             repo=match_repo, gateway=gw, seed=seed,
                             seat_meta=seat_meta, stop_flag=stop)

        async def _run() -> None:
            try:
                await runner.run()
            except Exception:
                import logging

                logging.getLogger(__name__).exception("match %s 运行失败", match_id)
                await match_repo.update_match(match_id, status="stopped")
            finally:
                runners.pop(match_id, None)

        runners[match_id] = runner
        asyncio.get_running_loop().create_task(_run())

    @app.get("/api/matches")
    async def list_matches() -> list[dict[str, Any]]:
        return await match_repo.list_matches()

    @app.get("/api/matches/{match_id}")
    async def get_match(match_id: int) -> dict[str, Any]:
        m = await match_repo.get_match(match_id)
        if m is None:
            raise HTTPException(status_code=404, detail="对局不存在")
        return m

    @app.get("/api/matches/{match_id}/events")
    async def list_events(match_id: int, after_seq: int = Query(0),
                          view: str = Query("immersive")) -> list[dict[str, Any]]:
        m = await match_repo.get_match(match_id)
        if m is None:
            raise HTTPException(status_code=404, detail="对局不存在")
        events = await match_repo.list_events(match_id, after_seq=after_seq, view=view)
        return [_event_dict(e) for e in events]

    @app.get("/api/matches/{match_id}/stream")
    async def stream(match_id: int, view: str = Query("immersive"),
                     last_event_id: int = 0):
        """SSE：Last-Event-ID/last_event_id 之后先补发再持续推送。"""
        m = await match_repo.get_match(match_id)
        if m is None:
            raise HTTPException(status_code=404, detail="对局不存在")

        async def gen():
            seq = last_event_id
            idle = 0.0
            while True:
                events = await match_repo.list_events(match_id, after_seq=seq, view=view)
                for ev in events:
                    yield _sse_frame(ev["seq"], _event_dict(ev))
                    seq = ev["seq"]
                    idle = 0.0
                if idle > 0:
                    yield ": keepalive\n\n"
                await asyncio.sleep(0.4)
                idle += 0.4
                # 对局结束且已追平 → 收流
                cur = await match_repo.get_match(match_id)
                if cur and cur["status"] in ("finished", "stopped") and not events:
                    yield "event: match_finished\ndata: {}\n\n"
                    break

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache",
                                          "X-Accel-Buffering": "no"})

    @app.get("/api/matches/{match_id}/usage")
    async def usage(match_id: int) -> dict[str, Any]:
        return await usage_repo.summarize(match_id)

    @app.post("/api/matches/{match_id}/stop")
    async def stop(match_id: int) -> dict[str, Any]:
        flag = stop_flags.get(match_id)
        if flag is not None:
            flag.set()
        return {"ok": True}

    @app.get("/api/catalog/boards")
    async def boards() -> list[dict[str, Any]]:
        return [dict(v, id=k) for k, v in PRESETS.items()]

    @app.get("/api/catalog/personas")
    async def personas() -> list[dict[str, Any]]:
        return DEFAULT_PERSONAS

    @app.get("/api/catalog/providers")
    async def providers() -> list[dict[str, Any]]:
        # 脱敏：只给 id/base_url/model 列表，不给 key 相关字段值（字段名仅示意）
        return [{"id": p["id"], "base_url": p["base_url"],
                 "models": [m["id"] for m in p["models"]]} for p in DEFAULT_PROVIDERS]

    return app


def _event_dict(e) -> dict[str, Any]:
    return {"seq": e.seq, "type": e.type, "day_index": e.day_index,
            "phase": e.phase, "payload": e.payload}


def _sse_frame(seq: int, ev: dict[str, Any]) -> str:
    return f"id: {seq}\nevent: game_event\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"
