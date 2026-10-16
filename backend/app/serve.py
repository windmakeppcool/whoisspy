"""常驻对局服务（docs/backend/15-serve.md）：WS 直播帧推流 + 节奏控制。

serve 模式是 CLI 扩展（main.py --serve），非新框架：建局/跑局/落库/导出复用
既有执行序；本模块只做 ①事件流 → 直播帧增量分解（与 export._segments 同构，
不新增事件解释，P5）②节奏 gate（pause/frame/resume/speed）③消息分发。
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

import websockets

from app.config import mock_seats, real_seats
from app.events import Event
from app.export import (
    _fold_one,
    _seg_key,
    _seg_label,
    _visible,
    _vote_round,
    build_export,
    export_match_files,
    personas_meta,
    seat_rows,
)
from app.flow import MatchRun, run_match
from app.llm import LLMGateway, TraceRecorder
from app.rules import MAX_DAYS, ROLES, WOLF_MEETING_ROUNDS
from app.state import GameState
from app.store import Store

# 对局进行中时允许第二个 create 之前的最小间隔由客户端控制；
# 帧推送目标缺失（断线）时直接丢弃帧——事件已落库，重连 sync 可恢复（15-serve 一）。


# ---------- 节奏控制 ----------

class PaceController:
    """节奏控制（15-serve 三）：pause 在事件原子粒度 gate flow；frame 放行一个等待者。

    - `pause()`：flow 在下一次 `wait()` 处停住（ask 入口 / emit 原子）；
    - `frame()`：暂停态下放行**恰好一个**等待者（逐帧观赛）；
    - `resume()`：解除暂停，放行所有阻塞者；
    - `interval`：帧投递间隔秒数（speed，0 = 立即），只作用于投递侧。
    """

    def __init__(self, interval: float = 0.0) -> None:
        self.paused = False
        self.interval = interval
        self._gate = asyncio.Event()
        self._tokens = 0  # frame 放行额度（每 frame +1，每通过一个等待者 -1）

    def pause(self) -> None:
        self.paused = True
        self._gate.clear()

    def resume(self) -> None:
        self.paused = False
        self._gate.set()

    def frame(self) -> None:
        """放行一个等待者（非暂停态忽略）。"""
        if self.paused:
            self._tokens += 1
            self._gate.set()

    async def wait(self) -> None:
        """暂停点：paused 时阻塞到 resume 或被 frame 放行一次。"""
        while self.paused:
            await self._gate.wait()
            if self._tokens > 0:
                self._tokens -= 1
                return
            if not self.paused:
                return  # resume 唤醒
            self._gate.clear()  # 额度被其他等待者取走 → 重新等


# ---------- 直播帧增量分解 ----------

class StreamProjector:
    """事件流 → 直播帧增量（与 export._segments 同构，见 15-serve 二）。

    同一分段键 / 同一可见性过滤 / 同一 present 投影；段末 stage 对**全量事件**
    （含视角外事件）折叠——增量帧 append 进展示文档后与静态导出完全一致。
    """

    def __init__(self, view: str = "god") -> None:
        self.view = view
        self.state = GameState(roles={}, alive={})
        self._current: dict[str, Any] | None = None

    def on_event(self, ev: Event) -> list[dict[str, Any]]:
        """逐条事件 → 帧列表（segment_open / line / segment_close）。"""
        frames: list[dict[str, Any]] = []
        visible = _visible(ev, self.view)
        if visible and (self._current is None or _seg_key(ev) != self._current["_key"]):
            if self._current is not None:
                frames.append(self._close())
            key = _seg_key(ev)
            label, day, is_night = _seg_label(key)
            self._current = {"_key": key, "label": label, "day_index": day,
                             "is_night": is_night, "votes": []}
            frames.append({"type": "segment_open", "label": label,
                           "day_index": day, "is_night": is_night})
        _fold_one(self.state, ev)
        if visible:
            line = _line_for(ev)
            if line is not None:
                frames.append(line)
            if ev.type == "vote.resolved" and self._current is not None:
                self._current["votes"].append(_vote_round(ev, self.state))
        return frames

    def close(self) -> list[dict[str, Any]]:
        """对局收尾：冲刷未关闭段的 segment_close（与静态导出的末段 stage 对齐）。"""
        if self._current is None:
            return []
        frames = [self._close()]
        self._current = None
        return frames

    def _close(self) -> dict[str, Any]:
        seg = self._current
        return {"type": "segment_close",
                "stage": {"alive": sorted(s for s in self.state.alive
                                          if self.state.alive[s]),
                          "sheriff": self.state.sheriff},
                "votes": seg["votes"]}


def _line_for(ev: Event) -> dict[str, Any] | None:
    """present 投影 → line 帧（与展示文档 entries 同构）。"""
    from app.present import present

    line = present(ev)
    if line is None:
        return None
    return {"type": "line", "kind": line.kind, "seat": line.seat, "text": line.text}


# ---------- 服务 ----------

@dataclass
class MatchContext:
    """一次建局的对局上下文（serve 单实例：同一时刻至多一局在跑）。"""

    run: MatchRun
    projector: StreamProjector
    mid: int
    seed: int
    task: asyncio.Task | None = field(default=None, init=False)


class ServeServer:
    """WS 常驻对局服务（15-serve）：握手 → create → 推流 → 收尾导出。

    单客户端假设（单机单窗口）：帧只推给当前活动连接；断线后对局照常跑完
    （事件已落库），重连后 `sync` 取当前前缀全量快照再续接增量帧。
    """

    def __init__(self, *, store: Store, base: Path, token: str,
                 mode: str = "mock", seed: int | None = None,
                 model: str | None = None,
                 wolf_rounds: int = WOLF_MEETING_ROUNDS,
                 max_days: int = MAX_DAYS, max_calls: int = 600,
                 trace_dir: Path | None = None) -> None:
        self.store = store
        self.base = base
        self.token = token
        self.mode = mode
        self.seed = seed
        self.model = model
        self.wolf_rounds = wolf_rounds
        self.max_days = max_days
        self.max_calls = max_calls
        self.trace_dir = trace_dir
        self._match: MatchContext | None = None
        self._sink: asyncio.Queue[dict[str, Any]] | None = None
        self._ws: websockets.Server | None = None

    # ---------- 生命周期 ----------

    async def start(self) -> int:
        """起回环 WS 监听，返回实际端口（stdout 首行由调用方打印）。"""
        self._ws = await websockets.serve(self._handler, "127.0.0.1", 0)
        assert self._ws.sockets is not None
        return int(self._ws.sockets[0].getsockname()[1])

    async def stop(self) -> None:
        """取消进行中的对局任务并关闭监听（事件已落库，可按回放查看残局）。"""
        if self._match is not None and self._match.task is not None:
            self._match.task.cancel()
            try:
                await self._match.task
            except (asyncio.CancelledError, Exception):
                pass
        if self._ws is not None:
            self._ws.close()
            await self._ws.wait_closed()

    # ---------- 连接 ----------

    async def _handler(self, ws: websockets.ServerConnection) -> None:
        """连接处理：握手 → 消息循环；pusher 从共享 sink 推流。"""
        try:
            first = json.loads(await asyncio.wait_for(ws.recv(), 30))
        except (asyncio.TimeoutError, websockets.ConnectionClosed):
            return
        if first.get("type") != "hello" or first.get("token") != self.token:
            await ws.close(code=4401, reason="握手失败")
            return
        await self._send(ws, {"type": "ok"})
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._sink = queue
        pusher = asyncio.create_task(self._pusher(ws, queue))
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                await self._dispatch(ws, msg)
        except websockets.ConnectionClosed:
            pass
        finally:
            pusher.cancel()
            if self._sink is queue:
                self._sink = None  # 断线：帧丢弃（事件已落库，sync 可恢复）

    async def _pusher(self, ws: websockets.ServerConnection,
                      queue: asyncio.Queue[dict[str, Any]]) -> None:
        """帧投递：取帧 → 按 pace.interval 间隔 → 发送（speed 只作用于投递侧）。"""
        try:
            while True:
                frame = await queue.get()
                pace = self._match.run.pace if self._match is not None else None
                if pace is not None and pace.interval > 0:
                    await asyncio.sleep(pace.interval)
                await self._send(ws, frame)
        except (websockets.ConnectionClosed, asyncio.CancelledError):
            pass

    @staticmethod
    async def _send(ws: websockets.ServerConnection, frame: dict[str, Any]) -> None:
        await ws.send(json.dumps(frame, ensure_ascii=False))

    # ---------- 消息分发 ----------

    async def _dispatch(self, ws: websockets.ServerConnection,
                        msg: dict[str, Any]) -> None:
        t = msg.get("type")
        try:
            if t == "create":
                await self._do_create(ws, msg)
            elif t == "pace":
                await self._do_pace(ws, msg)
            elif t == "sync":
                await self._do_sync(ws)
            elif t == "list":
                await self._do_list(ws)
            elif t == "export":
                await self._do_export(ws, msg)
            elif t == "action":
                await self._send(ws, {"type": "error",
                                      "message": "人类座位动作档 2 实现"})
            else:
                await self._send(ws, {"type": "error", "message": f"未知消息 {t}"})
        except ValueError as e:
            await self._send(ws, {"type": "error", "message": str(e)})

    # ---------- create ----------

    async def _do_create(self, ws: websockets.ServerConnection,
                         msg: dict[str, Any]) -> None:
        if self._match is not None:
            raise ValueError("已有对局进行中（单实例），请等待其结束")
        seed = int(msg.get("seed") or self.seed or int(time.time()))
        if self.mode == "real":
            seats, assignments = real_seats(self.base, seed=seed, model=self.model)
        else:
            seats = mock_seats()
            assignments = [{"seat": s["seat"], "persona_id": s["persona_id"],
                            "model": "mock", "basis": "mock",
                            "provider_id": "mock"} for s in seats]
        board = {"roles": dict(ROLES), "wolf_meeting_rounds": self.wolf_rounds,
                 "max_days": self.max_days, "model_assignments": assignments}
        mid = await self.store.create_match(seed=seed, board=board, seats=seats)

        trace: TraceRecorder | None = None
        if self.trace_dir is not None:
            self.trace_dir.mkdir(parents=True, exist_ok=True)
            trace = TraceRecorder(str(self.trace_dir / f"match-{mid}.jsonl"))

        run = MatchRun(
            match_id=mid, seed=seed, state=GameState(roles={}, alive={}),
            seats={s["seat"]: s for s in seats},
            gateway=LLMGateway(record=self.store.add_llm_call, trace=trace),
            store=self.store, max_calls=self.max_calls, max_days=self.max_days,
            wolf_meeting_rounds=self.wolf_rounds, model_assignments=assignments,
            trace=trace, pace=PaceController())
        if msg.get("paused"):
            run.pace.pause()
        ctx = MatchContext(run=run, projector=StreamProjector("god"),
                           mid=mid, seed=seed)
        self._match = ctx

        await self._send(ws, {"type": "ok", "match_id": mid})
        await self._send(ws, {"type": "match_open", "match": self._match_open(ctx)})
        ctx.task = asyncio.create_task(self._run_match(ctx))

    def _match_open(self, ctx: MatchContext) -> dict[str, Any]:
        """开局元信息（= 展示文档 match 字段，view 恒 god；role 由 seat_role 帧补齐）。"""
        m = {"match_id": ctx.mid, "seed": ctx.seed, "status": "running",
             "winner": None, "reason": None}
        board = {"roles": dict(ROLES), "wolf_meeting_rounds": self.wolf_rounds,
                 "max_days": self.max_days}
        rows = seat_rows([ctx.run.seats[s] for s in sorted(ctx.run.seats)],
                         personas_meta(self.base), include_role=False)
        return {**m, "board": board, "seats": rows,
                "model_assignments": ctx.run.model_assignments}

    # ---------- 对局任务 ----------

    async def _run_match(self, ctx: MatchContext) -> None:
        run = ctx.run
        run.on_event = lambda ev: self._on_event(ctx, ev)
        try:
            await run_match(run)
        except asyncio.CancelledError:
            raise
        finally:
            self._match = ctx  # 结束态保留（sync/list/export 可用）
            # 冲刷末段 stage/votes（流式增量帧与静态导出的对齐点）
            if self._sink is not None:
                for f in ctx.projector.close():
                    self._sink.put_nowait(f)
            await self._finish(ctx)

    def _on_event(self, ctx: MatchContext, ev: Event) -> None:
        """事件 → 帧（同步回调）：展示文档增量 + 直播新增帧（seat_role/终局）。"""
        frames = ctx.projector.on_event(ev)
        if ev.type == "role.dealt":
            frames.append({"type": "seat_role", "seat": int(ev.payload.get("seat") or 0),
                           "role": str(ev.payload.get("role", ""))})
        if self._sink is not None:
            for f in frames:
                self._sink.put_nowait(f)

    async def _finish(self, ctx: MatchContext) -> None:
        """对局收尾：usage 帧 → 终局帧 → 双视角导出 + 索引（复用 CLI 收尾）。"""
        mid = ctx.mid
        usage = await self.store.usage_summary(mid)
        events = ctx.run.events
        usage = {**usage,
                 "fallbacks": sum(1 for e in events if e.type == "player.fallback"),
                 "rule_errors": sum(1 for e in events if e.type == "rule.error")}
        finished = next((e for e in reversed(events) if e.type == "match.finished"),
                        None)
        stopped = next((e for e in reversed(events) if e.type == "match.stopped"),
                       None)
        if self._sink is not None:
            self._sink.put_nowait({"type": "usage", **usage})
            if finished is not None:
                self._sink.put_nowait(
                    {"type": "finished", "winner": finished.payload.get("winner"),
                     "reason": finished.payload.get("reason")})
            elif stopped is not None:
                self._sink.put_nowait(
                    {"type": "stopped", "reason": stopped.payload.get("reason")})
        await export_match_files(self.store, mid, self.base,
                                 out_dir=self.base / "exports")
        if ctx.run.trace is not None:
            ctx.run.trace.close()

    # ---------- 查询 ----------

    async def _do_sync(self, ws: websockets.ServerConnection) -> None:
        """当前前缀全量快照（= build_export，与增量帧同构）。"""
        if self._match is None:
            raise ValueError("尚无对局")
        ctx = self._match
        doc = build_export(
            match_id=ctx.mid, match_info=await self.store.load_match(ctx.mid),
            seats=await self.store.load_seats(ctx.mid),
            events=ctx.run.events, usage=await self.store.usage_summary(ctx.mid),
            view="god", personas=personas_meta(self.base))
        await self._send(ws, {"type": "snapshot", "doc": doc})

    async def _do_list(self, ws: websockets.ServerConnection) -> None:
        entries = []
        for m in await self.store.load_matches():
            seats = await self.store.load_seats(m["id"])
            entries.append({
                "match_id": m["id"], "seed": m["seed"],
                "status": m["status"],
                "winner": (m.get("result") or {}).get("winner"),
                "reason": (m.get("result") or {}).get("reason"),
                "player_count": len(seats),
                "exported_at": m["created_at"],
                "views": ["god", "public"] if m["status"] == "finished" else [],
            })
        await self._send(ws, {"type": "ok", "matches": entries})

    async def _do_export(self, ws: websockets.ServerConnection,
                         msg: dict[str, Any]) -> None:
        mid = int(msg.get("match_id") or 0)
        if mid <= 0 or await self.store.load_match(mid) is None:
            raise ValueError("对局不存在")
        await export_match_files(self.store, mid, self.base,
                                 out_dir=self.base / "exports")
        await self._send(ws, {"type": "ok"})

    # ---------- 节奏 ----------

    async def _do_pace(self, ws: websockets.ServerConnection,
                       msg: dict[str, Any]) -> None:
        if self._match is None:
            raise ValueError("尚无对局")
        pace = self._match.run.pace
        op = msg.get("op")
        if op == "pause":
            pace.pause()
        elif op == "resume":
            pace.resume()
        elif op == "frame":
            pace.frame()
        elif op == "speed":
            pace.interval = max(0.0, float(msg.get("value") or 0.0))
        else:
            raise ValueError(f"未知节奏操作 {op}")
        await self._send(ws, {"type": "ok"})