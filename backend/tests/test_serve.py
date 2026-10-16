"""serve 层测试（Red 先行）：docs/backend/15-serve.md 全规格。

覆盖：StreamProjector 增量帧与静态导出同构；PaceController 暂停/逐帧/恢复；
带 pace 的对局推进语义；WS 握手；端到端观战帧流；sync 快照；list/export。
"""

import asyncio
import json
from pathlib import Path

import pytest
import websockets

from app.export import _segments, build_export, index_entry
from app.flow import MatchRun, run_match
from app.llm import LLMGateway
from app.serve import PaceController, ServeServer, StreamProjector
from app.state import GameState
from app.store import Store

ROLES9 = {1: "wolf", 2: "wolf", 3: "wolf", 4: "seer", 5: "witch", 6: "hunter",
          7: "villager", 8: "villager", 9: "villager"}


@pytest.fixture
async def run_factory():
    stores: list[Store] = []

    async def _make(seed=42, max_calls=600):
        store = await Store.init(":memory:")
        stores.append(store)
        st = GameState(roles=dict(ROLES9), alive={s: True for s in ROLES9})
        seats = {i: {"seat": i, "role": "", "style": "", "strategy": "",
                     "model": "mock", "base_url": "", "api_key": "",
                     "price_per_mtok_in": 0.0, "price_per_mtok_out": 0.0}
                 for i in range(1, 10)}
        await store.create_match(seed=seed, board={}, seats=list(seats.values()))
        run = MatchRun(match_id=1, seed=seed, state=st, seats=seats,
                       gateway=LLMGateway(), store=store, max_calls=max_calls)
        return run

    yield _make
    for st in stores:
        await st.close()


# ---------- StreamProjector：增量帧 ≡ 静态分段 ----------

def _reconstruct(frames: list[dict]) -> list[dict]:
    """把直播帧流重建成展示文档段列表（segment_open → line* → segment_close）。"""
    segs: list[dict] = []
    cur: dict | None = None
    for f in frames:
        if f["type"] == "segment_open":
            cur = {"label": f["label"], "day_index": f["day_index"],
                   "is_night": f["is_night"], "entries": []}
            segs.append(cur)
        elif f["type"] == "line":
            cur["entries"].append({"kind": f["kind"], "seat": f["seat"],
                                   "text": f["text"]})
        elif f["type"] == "segment_close":
            cur["stage"] = f["stage"]
            if f["votes"]:
                cur["votes"] = f["votes"]
    return segs


async def test_projector与静态分段同构双视角(run_factory):
    """同一事件流：流式帧重建的段 ≡ export._segments（段界/行/votes/stage）。"""
    run = await run_factory(seed=42)
    await run_match(run)
    assert run.events, "mock 局应有事件"
    for view in ("god", "public"):
        proj = StreamProjector(view=view)
        frames: list[dict] = []
        for ev in run.events:
            frames.extend(proj.on_event(ev))
        frames.extend(proj.close())  # 收尾冲刷末段（与静态导出末段 stage 对齐）
        assert _reconstruct(frames) == _segments(run.events, view)


async def test_projector开局段与发牌(run_factory):
    run = await run_factory(seed=1)
    await run_match(run)
    proj = StreamProjector(view="god")
    frames: list[dict] = []
    for ev in run.events:
        frames.extend(proj.on_event(ev))
    opens = [f for f in frames if f["type"] == "segment_open"]
    assert opens[0]["label"] == "开局"
    assert opens[0]["is_night"] is False


# ---------- PaceController ----------

async def test_pace暂停阻塞与逐帧放行():
    pace = PaceController()
    assert pace.paused is False
    pace.pause()
    assert pace.paused is True
    t = asyncio.create_task(pace.wait())
    await asyncio.sleep(0.02)
    assert not t.done()  # 暂停时阻塞
    pace.frame()  # 放行一个原子
    await asyncio.wait_for(t, 0.2)
    assert t.done()


async def test_pace暂停并发等待者frame只放行一个():
    pace = PaceController()
    pace.pause()
    t1 = asyncio.create_task(pace.wait())
    t2 = asyncio.create_task(pace.wait())
    await asyncio.sleep(0.02)
    assert not t1.done() and not t2.done()
    pace.frame()
    await asyncio.sleep(0.05)
    assert t1.done() != t2.done()  # 恰好放行一个
    pace.resume()
    await asyncio.wait_for(asyncio.gather(t1, t2), 0.5)
    assert t1.done() and t2.done()


async def test_pace恢复后wait不阻塞():
    pace = PaceController()
    pace.pause()
    pace.resume()
    await asyncio.wait_for(pace.wait(), 0.2)


# ---------- pace × 对局 ----------

async def test_pace暂停对局与逐帧推进(run_factory):
    """暂停时事件流停在原子处；frame 放行一个事件；resume 跑完。"""
    run = await run_factory(seed=42)
    pace = PaceController()
    run.pace = pace
    pace.pause()
    task = asyncio.create_task(run_match(run))
    await asyncio.sleep(0.05)
    assert len(run.events) == 1  # match.created 后停在 emit 原子
    pace.frame()
    await asyncio.sleep(0.05)
    assert len(run.events) == 2  # match.started
    pace.resume()
    result = await asyncio.wait_for(task, 10)
    assert result is not None
    assert len(run.events) > 2


# ---------- WS 服务 ----------

async def _serve(tmp_path, **kw) -> tuple[ServeServer, int, Store]:
    store = await Store.init(":memory:")
    server = ServeServer(store=store, base=Path(tmp_path), token="t0ken",
                         mode="mock", seed=42, **kw)
    port = await server.start()
    return server, port, store


async def _hello(ws, token="t0ken"):
    await ws.send(json.dumps({"type": "hello", "token": token}))
    return json.loads(await ws.recv())


async def _recv_until(ws, ftype: str, timeout=30) -> dict:
    """循环收帧，跳过直播帧流，直到出现指定类型（应答与帧流同连接混流）。"""
    while True:
        f = json.loads(await asyncio.wait_for(ws.recv(), timeout))
        if f["type"] == ftype:
            return f


async def test_握手token不匹配断开(tmp_path):
    server, port, store = await _serve(tmp_path)
    try:
        uri = f"ws://127.0.0.1:{port}"
        async with websockets.connect(uri) as ws:
            await ws.send(json.dumps({"type": "hello", "token": "wrong"}))
            with pytest.raises(websockets.ConnectionClosed):
                await ws.recv()
    finally:
        await server.stop()
        await store.close()


async def test_首帧非hello断开(tmp_path):
    server, port, store = await _serve(tmp_path)
    try:
        uri = f"ws://127.0.0.1:{port}"
        async with websockets.connect(uri) as ws:
            await ws.send(json.dumps({"type": "create", "game": "werewolf",
                                      "board": {}, "seats": []}))
            with pytest.raises(websockets.ConnectionClosed):
                await ws.recv()
    finally:
        await server.stop()
        await store.close()


async def test_端到端观战帧流(tmp_path):
    """hello → create → match_open → 段/行帧流 → usage + finished。"""
    server, port, store = await _serve(tmp_path)
    try:
        uri = f"ws://127.0.0.1:{port}"
        async with websockets.connect(uri) as ws:
            ok = await _hello(ws)
            assert ok["type"] == "ok"
            await ws.send(json.dumps({"type": "create", "game": "werewolf",
                                      "board": {}, "seed": 42,
                                      "seats": [{"seat": i, "type": "llm"}
                                                for i in range(1, 10)]}))
            frames: list[dict] = []
            while True:
                f = json.loads(await asyncio.wait_for(ws.recv(), 30))
                frames.append(f)
                if f["type"] in ("finished", "stopped"):
                    break
        assert frames[0]["type"] == "ok"
        assert "match_id" in frames[0]
        assert frames[1]["type"] == "match_open"
        assert frames[1]["match"]["match_id"] == frames[0]["match_id"]
        assert frames[1]["match"]["seats"], "match_open 应带座位元信息"
        kinds = {f["type"] for f in frames}
        assert {"segment_open", "line", "segment_close"} <= kinds
        assert "usage" in kinds
        last = frames[-1]
        assert last["type"] in ("finished", "stopped")
        if last["type"] == "finished":
            assert last["winner"] in ("wolf", "good")
        # usage 在 finished 之前
        assert [f["type"] for f in frames].index("usage") < len(frames) - 1
        # 帧重建段与落库静态导出一致（两侧都过 JSON 层：帧流键为字符串）
        seg_frames = [f for f in frames if f["type"] in
                      ("segment_open", "line", "segment_close")]
        doc = build_export(match_id=frames[0]["match_id"],
                           match_info=await store.load_match(frames[0]["match_id"]),
                           seats=await store.load_seats(frames[0]["match_id"]),
                           events=await store.load_events(frames[0]["match_id"]),
                           usage=await store.usage_summary(frames[0]["match_id"]),
                           view="god")
        assert _reconstruct(seg_frames) == json.loads(
            json.dumps(doc["segments"], ensure_ascii=False))
        # 发牌元信息：seat_role 帧补齐 match.seats[].role
        seat_roles = {f["seat"]: f["role"] for f in frames
                      if f["type"] == "seat_role"}
        assert len(seat_roles) == 9
    finally:
        await server.stop()
        await store.close()


async def test_create后已有对局拒绝(tmp_path):
    server, port, store = await _serve(tmp_path)
    try:
        uri = f"ws://127.0.0.1:{port}"
        async with websockets.connect(uri) as ws:
            await _hello(ws)
            await ws.send(json.dumps({"type": "create", "game": "werewolf",
                                      "board": {}, "seats": []}))
            await _recv_until(ws, "ok", timeout=5)
            await _recv_until(ws, "match_open", timeout=5)
            # 对局进行中再建局 → error
            await ws.send(json.dumps({"type": "create", "game": "werewolf",
                                      "board": {}, "seats": []}))
            resp = await _recv_until(ws, "error", timeout=5)
            assert "进行中" in resp["message"]
    finally:
        await server.stop()
        await store.close()


async def test_paused开局与sync快照(tmp_path):
    """create 带 paused：事件停在开局；sync 返回当前前缀；frame 推进；resume 收尾。"""
    server, port, store = await _serve(tmp_path)
    try:
        uri = f"ws://127.0.0.1:{port}"
        async with websockets.connect(uri) as ws:
            await _hello(ws)
            await ws.send(json.dumps({"type": "create", "game": "werewolf",
                                      "board": {}, "seed": 42, "paused": True,
                                      "seats": []}))
            await _recv_until(ws, "ok", timeout=5)
            await _recv_until(ws, "match_open", timeout=5)
            await asyncio.sleep(0.05)
            await ws.send(json.dumps({"type": "sync"}))
            snap = await _recv_until(ws, "snapshot", timeout=5)
            doc = snap["doc"]
            assert doc["match"]["status"] == "running"
            assert len(doc["segments"]) == 1  # 停在开局段（match.created）
            assert doc["segments"][0]["label"] == "开局"
            assert doc["segments"][0]["entries"] == []  # 尚无上屏行
            # 逐帧推进：frame 数次后开局段出现发牌行
            for _ in range(4):
                await ws.send(json.dumps({"type": "pace", "op": "frame"}))
                await asyncio.sleep(0.02)
            await ws.send(json.dumps({"type": "sync"}))
            snap2 = await _recv_until(ws, "snapshot", timeout=5)
            entries2 = snap2["doc"]["segments"][0]["entries"]
            assert any(e["kind"] == "system" and "发牌" in e["text"]
                       for e in entries2)
            # resume 跑完
            await ws.send(json.dumps({"type": "pace", "op": "resume"}))
            while True:
                f = json.loads(await asyncio.wait_for(ws.recv(), 30))
                if f["type"] in ("finished", "stopped"):
                    break
    finally:
        await server.stop()
        await store.close()


async def test_list与export(tmp_path):
    server, port, store = await _serve(tmp_path)
    try:
        uri = f"ws://127.0.0.1:{port}"
        async with websockets.connect(uri) as ws:
            await _hello(ws)
            await ws.send(json.dumps({"type": "create", "game": "werewolf",
                                      "board": {}, "seed": 42, "seats": []}))
            while True:
                f = json.loads(await asyncio.wait_for(ws.recv(), 30))
                if f["type"] in ("finished", "stopped"):
                    break
            await ws.send(json.dumps({"type": "list"}))
            listing = json.loads(await asyncio.wait_for(ws.recv(), 5))
            assert listing["type"] == "ok"
            assert listing["matches"][0]["match_id"] == 1
            assert listing["matches"][0]["status"] == "finished"
            assert listing["matches"][0]["player_count"] == 9
            await ws.send(json.dumps({"type": "export", "match_id": 1}))
            resp = json.loads(await asyncio.wait_for(ws.recv(), 5))
            assert resp["type"] == "ok"
            out = Path(tmp_path) / "exports"
            assert (out / "match-1-god.json").exists()
            assert (out / "match-1-public.json").exists()
            assert (out / "index.json").exists()
            index = json.loads((out / "index.json").read_text(encoding="utf-8"))
            entry = index_entry(match_id=1, seed=42, status="finished",
                                winner=index["matches"][0]["winner"],
                                reason=index["matches"][0]["reason"],
                                player_count=9, exported_at="",
                                views=["god", "public"])
            assert index["matches"][0]["match_id"] == entry["match_id"]
    finally:
        await server.stop()
        await store.close()