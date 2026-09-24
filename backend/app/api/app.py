"""FastAPI 应用工厂：matches / events / stream(SSE) / stop / usage / catalog。

- 可见性过滤在 storage 出站层统一执行（支柱 3）
- 单板收敛 + 座位接入白名单 + 可选本地 token（安全约束见 docs/configuration.md）
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.config.loader import apply_boards, load_config, resolve_api_key
from app.engine.runner import MatchRunner
from app.export.dialog import render_dialog
from app.games.registry import DEFAULT_BOARD_ID, PRESETS, resolve_board
from app.llm.gateway import OpenAICompatGateway
from app.storage.repo import SqliteMatchRepository, SqliteUsageRepository

log = logging.getLogger(__name__)


class SeatIn(BaseModel):
    seat: int
    persona_id: str = "calm-analyst"
    name: str = ""
    # 接入方式二选一：
    # 1) provider_ref = "provider_id" 或 "provider_id/model_id"（引用 providers.json 预设，推荐）
    # 2) 显式 base_url + api_key_env + model（base_url 必须与 providers.json 中某条一致，
    #    否则拒绝——避免把真实 key 发到任意地址，见 docs/configuration.md 安全约束）
    provider_ref: str = ""
    base_url: str = ""
    api_key_env: str = ""
    model: str = ""  # 空串 = 未指定：persona 有绑定则用绑定，否则 mock


class CreateMatchIn(BaseModel):
    game_type: str = "werewolf"
    board: dict[str, Any] = Field(default_factory=lambda: {"id": DEFAULT_BOARD_ID})
    seats: list[SeatIn]


DEFAULT_CORS_ORIGINS = (
    "http://localhost:5173", "http://127.0.0.1:5173",   # 前端 dev（Vite）
    "http://localhost:4173", "http://127.0.0.1:4173",   # 前端 preview
    "http://localhost:3080", "http://127.0.0.1:3080",   # 本机观看台
)


def _cors_origins() -> list[str]:
    """允许的来源：默认本机常见端口；WHOISSPY_CORS_ORIGINS 可覆盖（逗号分隔，* 为全放行）。"""
    raw = os.environ.get("WHOISSPY_CORS_ORIGINS", "").strip()
    if not raw:
        return list(DEFAULT_CORS_ORIGINS)
    return [o.strip() for o in raw.split(",") if o.strip()]


def create_app(db_path: str | None = None, data_dir: str | None = None) -> FastAPI:
    # 配置 JSON 化（D13）：backend/data/*.json 为权威，缺文件回落内置默认；坏配置拒绝启动
    bundle = load_config(data_dir)
    apply_boards(bundle)

    match_repo = SqliteMatchRepository(db_path)
    usage_repo = SqliteUsageRepository(db_path)
    runners: dict[int, MatchRunner] = {}
    tasks: dict[int, asyncio.Task] = {}
    stop_flags: dict[int, asyncio.Event] = {}

    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        await match_repo.init()
        await usage_repo.init()
        try:
            yield
        finally:
            await _shutdown_runners()

    async def _shutdown_runners() -> None:
        """关停：先请求优雅停止，短暂等待后取消，然后**无论如何**清表并关闭仓储。

        否则正在跑的对局会往已 dispose 的引擎写事件；而「一局都没在跑」时也必须
        关闭两个 repository（早期版本在这里提前 return，导致引擎泄漏）。
        """
        try:
            if tasks:
                for flag in stop_flags.values():
                    flag.set()
                pending = list(tasks.values())
                done, still = await asyncio.wait(pending, timeout=1.5)
                for t in still:
                    t.cancel()
                await asyncio.gather(*still, return_exceptions=True)
                await asyncio.gather(*done, return_exceptions=True)
        finally:
            tasks.clear()
            runners.clear()
            stop_flags.clear()
            await match_repo.close()
            await usage_repo.close()

    app = FastAPI(title="whoisspy backend", lifespan=_lifespan)
    app.state.runners = runners
    app.state.tasks = tasks

    @app.middleware("http")
    async def _token_guard(request, call_next):
        """可选本地令牌：设置 WHOISSPY_API_TOKEN 后，所有请求都需携带该令牌。

        默认关闭（本机观赛工具），开启后能挡住「用户浏览器里的任意网页打本机端口」。
        """
        token = os.environ.get("WHOISSPY_API_TOKEN", "").strip()
        if token and request.method != "OPTIONS":
            supplied = (request.headers.get("x-api-token")
                        or request.headers.get("authorization", "").removeprefix("Bearer ").strip())
            if supplied != token:
                return JSONResponse({"detail": "缺少或错误的 API token"}, status_code=401)
        return await call_next(request)

    # CORS 必须最后添加（Starlette 后添加者在外层）：否则令牌中间件返回的 401
    # 不会带上 CORS 头，浏览器侧只能看到不透明的跨域失败。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Last-Event-ID", "X-API-Token", "Authorization"],
    )

    def _persona(persona_id: str) -> dict[str, Any]:
        for p in bundle.personas:
            if p["id"] == persona_id:
                return p
        raise HTTPException(status_code=422, detail=f"未知选手档案（persona_id）: {persona_id!r}")

    def _provider(provider_id: str) -> dict[str, Any]:
        for p in bundle.providers:
            if p["id"] == provider_id:
                return p
        raise HTTPException(status_code=422, detail=f"未知接入预设（provider_id）: {provider_id!r}")

    def _model_cfg(provider: dict[str, Any], model_id: str) -> dict[str, Any]:
        for m in provider.get("models", []):
            if m.get("id") == model_id:
                return m
        raise HTTPException(
            status_code=422,
            detail=f"模型 {model_id!r} 不属于接入预设 {provider['id']!r}")

    def _seat_access(s: SeatIn) -> dict[str, Any]:
        """解析座位接入快照：provider_id/base_url/api_key_env/model + 单价。

        优先级：provider_ref > 显式四字段 > persona 绑定 > mock。
        安全约束：任何真实接入的 base_url 必须与 providers.json 中某条一致，
        且其 api_key_env 必须能在环境变量里解析到非空 key（防止把真实 key 发到任意地址、
        也防止配错后整局静默走兜底）。
        """
        if s.provider_ref:
            pid, _, mid = s.provider_ref.partition("/")
            provider = _provider(pid)
            model_id = mid or (provider.get("models") or [{}])[0].get("id", "")
            return _access_from_provider(provider, _model_cfg(provider, model_id))
        if s.model or s.base_url or s.api_key_env:
            base_url = s.base_url
            if base_url:
                provider = next((p for p in bundle.providers
                                 if p.get("base_url") == base_url), None)
                if provider is None:
                    raise HTTPException(
                        status_code=422,
                        detail=f"base_url {base_url!r} 不在 providers.json 中；"
                               "请改用 provider_ref 引用已配置的接入")
            else:
                provider = {}
            model_id = s.model or "mock"
            if model_id == "mock":
                return {"provider_id": provider.get("id", ""), "base_url": "",
                        "api_key_env": "", "model": "mock",
                        "price_per_mtok_in": 0.0, "price_per_mtok_out": 0.0,
                        "price_per_mtok_cached_in": 0.0}
            model_cfg = _model_cfg(provider, model_id) if provider else {}
            return _access_from_provider(provider, model_cfg, api_key_env=s.api_key_env,
                                         model_id=model_id)
        persona = _persona(s.persona_id)
        pid, model = persona.get("provider_id"), persona.get("model")
        if pid and model:
            provider = _provider(pid)
            return _access_from_provider(provider, _model_cfg(provider, model))
        return {"provider_id": "", "base_url": "", "api_key_env": "", "model": "mock",
                "price_per_mtok_in": 0.0, "price_per_mtok_out": 0.0,
                "price_per_mtok_cached_in": 0.0}

    def _access_from_provider(provider: dict[str, Any], model_cfg: dict[str, Any],
                              *, api_key_env: str = "", model_id: str = "") -> dict[str, Any]:
        """按 provider 预设展开座位接入快照；key 必须能在环境变量里取到。"""
        env_name = api_key_env or provider.get("api_key_env", "")
        model = model_id or model_cfg.get("id", "") or "mock"
        price_in = float(model_cfg.get("price_per_mtok_in", 0.0) or 0.0)
        return {
            "provider_id": provider.get("id", ""),
            "base_url": provider.get("base_url", ""),
            "api_key_env": env_name,
            "model": model,
            "price_per_mtok_in": price_in,
            "price_per_mtok_out": float(model_cfg.get("price_per_mtok_out", 0.0) or 0.0),
            "price_per_mtok_cached_in": float(
                model_cfg.get("price_per_mtok_cached_in", price_in) or 0.0),
            "api_key": resolve_api_key(env_name),
        }

    def _validate_access(access: dict[str, Any], seat: int) -> None:
        """真实接入必须能拿到 key 且 base_url 齐备（mock 豁免）。"""
        if access["model"] == "mock" and not access["base_url"]:
            return
        if not access["base_url"]:
            raise HTTPException(status_code=422,
                                detail=f"座位 {seat} 指定了真实模型 {access['model']!r} 但没有 base_url")
        if not access["api_key"]:
            raise HTTPException(
                status_code=422,
                detail=f"座位 {seat} 需要环境变量 {access['api_key_env'] or '(未配置)'}，"
                       "但当前环境中取不到非空 key")

    @app.post("/api/matches")
    async def create_match(body: CreateMatchIn) -> dict[str, Any]:
        try:
            game, spec = resolve_board(body.board)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        if body.game_type and body.game_type != spec.game_type:
            raise HTTPException(status_code=422,
                                detail=f"game_type {body.game_type!r} 与板子不符"
                                       f"（板子是 {spec.game_type!r}）")
        if len(body.seats) != spec.player_count:
            raise HTTPException(status_code=422,
                                detail=f"板子需要 {spec.player_count} 人，收到 {len(body.seats)} 个座位")
        seat_nums = sorted(s.seat for s in body.seats)
        if seat_nums != list(range(1, spec.player_count + 1)):
            raise HTTPException(
                status_code=422,
                detail=f"座位号必须恰好是 1..{spec.player_count} 且不重复，收到 {seat_nums}")
        import random

        seed = random.randrange(1, 2**31)
        seats = []
        for s in sorted(body.seats, key=lambda x: x.seat):
            access = _seat_access(s)
            _validate_access(access, s.seat)
            persona = _persona(s.persona_id)
            seats.append({
                "seat": s.seat, "name": s.name or persona["name"],
                "persona_id": s.persona_id,
                # 人设与接入在创建时一次性固化（D10/D11）：改 personas.json 不影响历史对局
                "style": persona.get("style", ""), "strategy": persona.get("strategy", ""),
                "provider_id": access["provider_id"],
                "base_url": access["base_url"], "api_key_env": access["api_key_env"],
                "model": access["model"],
                "price_per_mtok_in": access["price_per_mtok_in"],
                "price_per_mtok_out": access["price_per_mtok_out"],
                "price_per_mtok_cached_in": access["price_per_mtok_cached_in"],
                "role": "",
            })
        m = await match_repo.create_match(
            game_type=spec.game_type, ruleset=spec.ruleset,
            board={"id": body.board.get("id") or "custom", "ruleset": spec.ruleset,
                   "roles": spec.roles, "wolf_meeting_rounds": spec.wolf_meeting_rounds,
                   "max_days": spec.max_days,
                   **({"model_assignments": body.board["model_assignments"]}
                      if body.board.get("model_assignments") else {})},
            rng_seed=seed, seats=seats)
        _spawn_runner(m["id"], game, spec, seed, m["seats"],
                      board_id=str(m["board"].get("id") or ""))
        return m

    def _spawn_runner(match_id: int, game, spec, seed: int, seats: list[dict],
                      board_id: str = "") -> None:
        # 座位快照来自 match_seat（创建时固化）：历史对局不依赖后续配置变更（D10/D11）。
        # api_key_env → 实际 key 只解析进内存 seat_meta，落库仍只有变量名（安全规范）。
        seat_meta = {s["seat"]: {"model": s["model"], "base_url": s["base_url"],
                                 "api_key_env": s["api_key_env"],
                                 "api_key": resolve_api_key(s["api_key_env"]),
                                 "style": s.get("style", ""),
                                 "strategy": s.get("strategy", ""),
                                 "price_per_mtok_in": s.get("price_per_mtok_in", 0.0),
                                 "price_per_mtok_out": s.get("price_per_mtok_out", 0.0),
                                 "price_per_mtok_cached_in": s.get("price_per_mtok_cached_in", 0.0),
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
                             seat_meta=seat_meta, stop_flag=stop,
                             board_id=board_id)

        async def _finish(reason: str) -> None:
            """收尾：把中断/异常的对局落成 stopped，绝不留下 running 僵尸。"""
            try:
                got = await match_repo.get_match(match_id)
                if got is not None and got["status"] in ("created", "running"):
                    await match_repo.update_match(match_id, status="stopped",
                                                  result={"winner": None, "reason": reason})
            except Exception:  # 关停竞态下尽力而为
                log.warning("match %s 收尾失败（%s）", match_id, reason)

        async def _run() -> None:
            try:
                await runner.run()
            except asyncio.CancelledError:
                await _finish("服务关闭，对局被中断")
                raise
            except Exception:
                log.exception("match %s 运行失败", match_id)
                await _finish("对局运行异常")
            finally:
                runners.pop(match_id, None)
                stop_flags.pop(match_id, None)
                tasks.pop(match_id, None)

        runners[match_id] = runner
        tasks[match_id] = asyncio.get_running_loop().create_task(_run())

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
    async def list_events(match_id: int, request: Request, after_seq: int | None = Query(None),
                          view: str = Query("immersive")) -> list[dict[str, Any]]:
        """事件回放。游标取 after_seq，缺省时回落到 SSE 约定的 Last-Event-ID 头。"""
        m = await match_repo.get_match(match_id)
        if m is None:
            raise HTTPException(status_code=404, detail="对局不存在")
        cursor = after_seq if after_seq is not None else _cursor_from_header(request)
        events = await match_repo.list_events(match_id, after_seq=cursor, view=view)
        return [_event_dict(e) for e in events]

    @app.get("/api/matches/{match_id}/stream")
    async def stream(match_id: int, request: Request, view: str = Query("immersive"),
                     last_event_id: int | None = None):
        """SSE：从 last_event_id（或 Last-Event-ID 头）之后先补发，再持续推送。"""
        m = await match_repo.get_match(match_id)
        if m is None:
            raise HTTPException(status_code=404, detail="对局不存在")
        start_seq = last_event_id if last_event_id is not None else _cursor_from_header(request)

        async def gen():
            seq = start_seq
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
        m = await match_repo.get_match(match_id)
        if m is None:
            raise HTTPException(status_code=404, detail="对局不存在")
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
        m = await match_repo.get_match(match_id)
        if m is None:
            raise HTTPException(status_code=404, detail="对局不存在")
        flag = stop_flags.get(match_id)
        if flag is not None:
            flag.set()
            return {"ok": True, "stopping": True}
        # 已结束/未在跑：幂等返回
        return {"ok": True, "stopping": False}

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


def _cursor_from_header(request: Request) -> int:
    """SSE 断线重连游标：Last-Event-ID 头（浏览器 EventSource 自动带上）→ int。"""
    raw = request.headers.get("last-event-id", "").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def _event_dict(e) -> dict[str, Any]:
    return {"seq": e.seq, "type": e.type, "day_index": e.day_index,
            "phase": e.phase, "payload": e.payload,
            "vis": {"level": e.vis.level, "seats": e.vis.seats}}


def _sse_frame(seq: int, ev: dict[str, Any]) -> str:
    return f"id: {seq}\nevent: game_event\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"
