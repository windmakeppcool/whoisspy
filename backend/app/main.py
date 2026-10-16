"""CLI 入口（docs/backend/12-cli.md）：python -m app.main [选项]。

跑一局标准 9 人狼人杀 → 事件落 SQLite → 导出对话 JSON。
stdout 逐事件直播（present 投影）；退出码：0 分出胜负 / 2 终止 / 3 配置错误。
--serve 常驻对局服务（15-serve.md）：WS 直播帧推流，协议见 docs/backend/15-serve.md。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

from app.config import mock_seats, real_seats
from app.events import Event
from app.export import build_export, export_match_files, personas_meta
from app.flow import MatchRun, run_match
from app.llm import LLMGateway, TraceRecorder
from app.present import present
from app.rules import MAX_DAYS, ROLES, WOLF_MEETING_ROUNDS
from app.serve import ServeServer
from app.state import GameState
from app.store import Store


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="whoisspy headless 对局引擎")
    parser.add_argument("--mock", action="store_true", help="mock 模式（默认）")
    parser.add_argument("--real", action="store_true", help="真实 LLM（providers.json + .env）")
    parser.add_argument("--seed", type=int, default=None, help="随机种子（缺省取当前时间）")
    parser.add_argument("--db", default=None, help="SQLite 路径（默认 data/whoisspy.db）")
    parser.add_argument("--out", default=None, help="导出 JSON 路径（默认 exports/ 下双视角+索引）")
    parser.add_argument("--view", choices=("god", "public", "both"), default=None,
                        help="导出视角（缺省 both：双视角文件 + index.json；配 --out 时回落 god）")
    parser.add_argument("--trace", default=None, help="开启调用留痕目录（JSONL）")
    parser.add_argument("--model", default=None, help="real 模式把分配池收窄为单模型")
    parser.add_argument("--max-days", type=int, default=MAX_DAYS, help="天数上限")
    parser.add_argument("--wolf-rounds", type=int, default=WOLF_MEETING_ROUNDS,
                        help="狼队夜聊轮数")
    parser.add_argument("--max-calls", type=int, default=600, help="单局调用数护栏")
    parser.add_argument("--serve", action="store_true",
                        help="常驻对局服务模式（WS，协议见 docs/backend/15-serve.md）")
    parser.add_argument("--token", default=None, help="serve 模式握手 token")
    parser.add_argument("--base-dir", default=None,
                        help="配置/导出根目录（缺省 cwd；Electron 传本地数据集中目录）")
    args = parser.parse_args(argv)
    if not args.mock and not args.real:
        args.mock = True  # 缺省 mock 模式
    if args.serve and not args.token:
        raise SystemExit("--serve 必须配合 --token <t>（握手 token，不落日志/不入库）")
    if args.view is None:
        # 显式 --out 是单文件归档（旧行为回落 god）；否则缺省双视角 both
        args.view = "god" if args.out else "both"
    return args


async def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    base = Path(args.base_dir) if args.base_dir else Path.cwd()
    try:
        if args.serve:
            return await _serve_main(args, base)
        return await _run(args, base)
    except ValueError as e:
        print(f"配置错误：{e}")
        return 3


async def _serve_main(args: argparse.Namespace, base: Path) -> int:
    """serve 模式（12-cli 〇 / 15-serve）：WS 常驻，收 create 跑对局推直播帧。"""
    db_path = Path(args.db) if args.db else base / "data" / "whoisspy.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    store = await Store.init(str(db_path))
    server = ServeServer(
        store=store, base=base, token=args.token,
        mode="real" if args.real else "mock", seed=args.seed, model=args.model,
        wolf_rounds=args.wolf_rounds, max_days=args.max_days,
        max_calls=args.max_calls,
        trace_dir=Path(args.trace) if args.trace else None)
    try:
        port = await server.start()
        print(port, flush=True)  # stdout 首行：实际端口（Electron main 读取）
        print(f"serve 模式：ws://127.0.0.1:{port}（token 已注入，不打印）")
        await asyncio.Event().wait()  # 常驻
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await server.stop()
        await store.close()
    return 0


async def _run(args: argparse.Namespace, base: Path) -> int:
    if args.out and args.view == "both":
        # --out 是单文件归档路径，与双视角导出互斥（12-cli 四）
        raise ValueError("--out 与 --view both 不能同时使用；请显式指定 god 或 public")
    seed = args.seed if args.seed is not None else int(time.time())
    if args.real:
        seats, assignments = real_seats(base, seed=seed, model=args.model)
        print("模型分配：")
        for a in assignments:
            print(f"  {a['seat']}号 {a['persona_id']} -> {a['model']} ({a['basis']})")
    else:
        seats = mock_seats()
        assignments = [{"seat": s["seat"], "persona_id": s["persona_id"],
                        "model": "mock", "basis": "mock", "provider_id": "mock"}
                       for s in seats]
        print("模型分配：全部 mock（--real 接入真实 LLM）")

    db_path = Path(args.db) if args.db else base / "data" / "whoisspy.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    store = await Store.init(str(db_path))
    board = {"roles": dict(ROLES), "wolf_meeting_rounds": args.wolf_rounds,
             "max_days": args.max_days, "model_assignments": assignments}
    mid = await store.create_match(seed=seed, board=board, seats=seats)

    trace: TraceRecorder | None = None
    if args.trace:
        trace_dir = Path(args.trace)
        trace_dir.mkdir(parents=True, exist_ok=True)
        trace = TraceRecorder(str(trace_dir / f"match-{mid}.jsonl"))

    run = MatchRun(
        match_id=mid, seed=seed, state=GameState(roles={}, alive={}),
        seats={s["seat"]: s for s in seats},
        gateway=LLMGateway(record=store.add_llm_call, trace=trace),
        store=store, max_calls=args.max_calls, max_days=args.max_days,
        wolf_meeting_rounds=args.wolf_rounds, model_assignments=assignments,
        trace=trace)
    run.on_event = lambda ev: _live(ev)  # 终端直播（P5：present 唯一投影）

    code = 0
    try:
        result = await run_match(run)
        if result is None:
            code = 2  # stopped（超限/流程异常）
    except (KeyboardInterrupt, asyncio.CancelledError):
        await run.emit("match.stopped", {"reason": "手动终止"})
        await run.store.finalize_match(mid, "stopped",
                                       {"winner": None, "reason": "手动终止"})
        code = 2
    finally:
        await _finish(run, store, args, mid, base)
        if trace is not None:
            trace.close()
    return code


def _fmt_cost(micros: int) -> str:
    return f"¥{micros / 1e6:.2f}" if micros else "¥0.00"


def _live(ev: Event) -> None:
    line = present(ev)
    if line is not None:
        print(line.text)


async def _finish(run: MatchRun, store: Store, args: argparse.Namespace,
                  mid: int, base: Path) -> None:
    """用量汇总打印 + 导出 JSON + 关闭 DB。"""
    m = await store.load_match(mid)
    usage = await store.usage_summary(mid)
    fallbacks = sum(1 for e in run.events if e.type == "player.fallback")
    rule_errors = sum(1 for e in run.events if e.type == "rule.error")
    result = (m or {}).get("result") or {}
    if result.get("winner"):
        camp = "狼人阵营" if result["winner"] == "wolf" else "好人阵营"
        print(f"🏁 对局结束：{camp}获胜（{result.get('reason', '')}）")
    else:
        print(f"⏹ 对局终止（{(m or {}).get('status', '?')}）")
    print(f"用量：{usage['calls']} 次调用"
          f" / {usage['prompt_tokens'] + usage['completion_tokens']} tokens"
          f" / {_fmt_cost(usage['cost_micros'])}"
          f"（缓存命中 {usage['cache_hit_rate']:.0%}）"
          f" / 兜底 {fallbacks} 次 / 规则异常 {rule_errors} 次")

    if args.out:
        # 单文件归档（--view 生效，不更新索引）
        events = await store.load_events(mid)
        seats = await store.load_seats(mid)
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        doc = build_export(match_id=mid, match_info=m or {}, seats=seats,
                           events=events, usage=usage, view=args.view,
                           personas=personas_meta(base))
        out.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"导出：{args.out}")
    else:
        # 缺省：双视角文件 + 合并更新对局索引（12-cli 四 / 11-export 五）
        await export_match_files(store, mid, base)
        print(f"导出：exports/match-{mid}-god.json、exports/match-{mid}-public.json"
              " + index.json")
    await store.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))