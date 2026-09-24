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
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.config.loader import apply_boards, load_config, resolve_api_key
from app.engine.runner import MatchRunner
from app.export.dialog import render_dialog
from app.games.registry import PRESETS, resolve_board
from app.llm.gateway import OpenAICompatGateway
from app.storage.repo import SqliteMatchRepository, SqliteUsageRepository


class SeatIn(BaseModel):
    seat: int
    persona_id: str = "calm-analyst"
    name: str = ""
    base_url: str = ""
    api_key_env: str = ""
    model: str = ""  # 空串 = 未指定：persona 有绑定则用绑定，否则 mock


class CreateMatchIn(BaseModel):
    game_type: str = "werewolf"
    board: dict[str, Any] = Field(default_factory=lambda: {"id": "p6-classic"})
    seats: list[SeatIn]


def create_app(db_path: str | None = None, data_dir: str | None = None) -> FastAPI:
    # 配置 JSON 化（D13）：backend/data/*.json 为权威，缺文件回落内置默认；坏配置拒绝启动
    bundle = load_config(data_dir)
    apply_boards(bundle)

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
    app.state.runners = runners
    stop_flags: dict[int, asyncio.Event] = {}

    def _persona(persona_id: str) -> dict[str, Any]:
        for p in bundle.personas:
            if p["id"] == persona_id:
                return p
        return bundle.personas[0]

    def _seat_access(s: SeatIn) -> tuple[str, str, str]:
        """座位接入三元组 (base_url, api_key_env, model)。

        显式指定优先；未指定（空串）且 persona 有 provider/model 绑定 → 用绑定；
        都没有 → mock。D18：选手卡 = 性格 + 用哪个模型打。
        """
        if s.model or s.base_url or s.api_key_env:
            return s.base_url, s.api_key_env, s.model or "mock"
        persona = _persona(s.persona_id)
        pid, model = persona.get("provider_id"), persona.get("model")
        if pid and model:
            provider = next((p for p in bundle.providers if p["id"] == pid), None)
            if provider is not None:
                return provider.get("base_url", ""), provider.get("api_key_env", ""), model
        return "", "", "mock"

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
        seats = []
        for s in sorted(body.seats, key=lambda x: x.seat):
            base_url, api_key_env, model = _seat_access(s)
            seats.append({
                "seat": s.seat, "name": s.name or _persona(s.persona_id)["name"],
                "persona_id": s.persona_id, "base_url": base_url,
                "api_key_env": api_key_env, "model": model, "role": "",
            })
        m = await match_repo.create_match(
            game_type=body.game_type, ruleset=spec.ruleset,
            board={"id": body.board.get("id"), "ruleset": spec.ruleset,
                   "roles": spec.roles, "wolf_meeting_rounds": spec.wolf_meeting_rounds,
                   "max_days": spec.max_days,
                   **({"model_assignments": body.board["model_assignments"]}
                      if body.board.get("model_assignments") else {})},
            rng_seed=seed, seats=seats)
        _spawn_runner(m["id"], game, spec, seed, seats)
        return m

    def _spawn_runner(match_id: int, game, spec, seed: int, seats: list[dict]) -> None:
        # api_key_env → 实际 key 只解析进内存 seat_meta，落库仍只有变量名（安全规范）
        seat_meta = {s["seat"]: {"model": s["model"], "base_url": s["base_url"],
                                 "api_key_env": s["api_key_env"],
                                 "api_key": resolve_api_key(s["api_key_env"]),
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
                    # Event 是数据类：用属性访问，不能用下标
                    yield _sse_frame(ev.seq, _event_dict(ev))
                    seq = ev.seq
                    idle = 0.0
                if idle > 0:
                    yield ": keepalive\n\n"
                await asyncio.sleep(0.4)
                idle += 0.4
                # 对局结束 → 补拉 sleep 窗口内的剩余事件后再收流
                # （status 翻转前事件已全部落库，补拉结果即为全集，避免丢事件）
                cur = await match_repo.get_match(match_id)
                if cur and cur["status"] in ("finished", "stopped"):
                    tail = await match_repo.list_events(
                        match_id, after_seq=seq, view=view)
                    for ev in tail:
                        yield _sse_frame(ev.seq, _event_dict(ev))
                        seq = ev.seq
                    yield "event: match_finished\ndata: {}\n\n"
                    break

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache",
                                          "X-Accel-Buffering": "no"})

    @app.get("/api/matches/{match_id}/usage")
    async def usage(match_id: int) -> dict[str, Any]:
        return await usage_repo.summarize(match_id)

    @app.get("/api/matches/{match_id}/export")
    async def export_dialog(match_id: int) -> JSONResponse:
        """导出整局对话 JSON（上帝视角），用于离线复盘。"""
        m = await match_repo.get_match(match_id)
        if m is None:
            raise HTTPException(status_code=404, detail="对局不存在")
        # view=god 获取全量事件
        events = await match_repo.list_events(match_id, after_seq=0, view="god")
        data = render_dialog(match_id=match_id, game_type=m["game_type"], events=events)
        return JSONResponse(
            content=data,
            headers={
                "Content-Disposition": f"attachment; filename=\"match-{match_id}-dialog.json\""
            },
        )

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
        return bundle.personas

    @app.get("/api/catalog/providers")
    async def providers() -> list[dict[str, Any]]:
        # 脱敏：只给 id/base_url/model 列表，不给 api_key_env（变量名也不外泄）
        return [{"id": p["id"], "base_url": p["base_url"],
                 "models": [m["id"] for m in p["models"]]} for p in bundle.providers]

    return app


def _event_dict(e) -> dict[str, Any]:
    return {"seq": e.seq, "type": e.type, "day_index": e.day_index,
            "phase": e.phase, "payload": e.payload,
            "vis": {"level": e.vis.level, "seats": e.vis.seats}}


def _sse_frame(seq: int, ev: dict[str, Any]) -> str:
    return f"id: {seq}\nevent: game_event\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"
