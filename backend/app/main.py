"""CLI 入口（docs/backend/12-cli.md）：python -m app.main [选项]。

跑一局标准 9 人狼人杀 → 事件落 SQLite → 导出对话 JSON。
stdout 逐事件直播（present 投影）；退出码：0 分出胜负 / 2 终止 / 3 配置错误。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from app.config import build_seats, load_env_file, load_personas, load_providers
from app.events import Event
from app.export import build_export
from app.flow import MatchRun, run_match
from app.llm import LLMGateway, TraceRecorder
from app.present import present
from app.rules import MAX_DAYS, ROLES, WOLF_MEETING_ROUNDS
from app.state import GameState
from app.store import Store


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="whoisspy headless 对局引擎")
    parser.add_argument("--mock", action="store_true", help="mock 模式（默认）")
    parser.add_argument("--real", action="store_true", help="真实 LLM（providers.json + .env）")
    parser.add_argument("--seed", type=int, default=None, help="随机种子（缺省取当前时间）")
    parser.add_argument("--db", default=None, help="SQLite 路径（默认 data/whoisspy.db）")
    parser.add_argument("--out", default=None, help="导出 JSON 路径（默认 exports/ 下）")
    parser.add_argument("--view", choices=("god", "public"), default="god", help="导出视角")
    parser.add_argument("--trace", default=None, help="开启调用留痕目录（JSONL）")
    parser.add_argument("--model", default=None, help="real 模式把分配池收窄为单模型")
    parser.add_argument("--max-days", type=int, default=MAX_DAYS, help="天数上限")
    parser.add_argument("--wolf-rounds", type=int, default=WOLF_MEETING_ROUNDS,
                        help="狼队夜聊轮数")
    parser.add_argument("--max-calls", type=int, default=600, help="单局调用数护栏")
    args = parser.parse_args(argv)
    if not args.mock and not args.real:
        args.mock = True  # 缺省 mock 模式
    return args


def _mock_seats(n_players: int = 9) -> list[dict[str, Any]]:
    return [{"seat": i, "persona_id": f"mock-{i}", "style": "", "strategy": "",
             "provider_id": "mock", "base_url": "", "api_key_env": "",
             "model": "mock", "api_key": "",
             "price_per_mtok_in": 0.0, "price_per_mtok_out": 0.0,
             "price_per_mtok_cached_in": None}
            for i in range(1, n_players + 1)]


def _real_seats(args: argparse.Namespace,
                base: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """真实模式：加载配置 + key 预检 + 座位构建（persona 绑定 > 池内随机）。"""
    load_env_file(str(base / "data" / ".env"))
    providers = load_providers(str(base / "data" / "providers.json"))
    personas = load_personas(str(base / "data" / "personas.json"))
    seats, assignments = build_seats(
        n_players=9, personas=personas.personas, providers=providers.providers,
        env=os.environ, model=args.model,
        seed=args.seed if args.seed is not None else 0)
    for s in seats:
        s["api_key"] = os.environ.get(s["api_key_env"], "")  # 运行时解析进内存
    return seats, assignments


def _fmt_cost(micros: int) -> str:
    return f"¥{micros / 1e6:.2f}" if micros else "¥0.00"


async def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    base = Path.cwd()
    try:
        return await _run(args, base)
    except ValueError as e:
        print(f"配置错误：{e}")
        return 3


async def _run(args: argparse.Namespace, base: Path) -> int:
    seed = args.seed if args.seed is not None else int(time.time())
    if args.real:
        seats, assignments = _real_seats(args, base)
        print("模型分配：")
        for a in assignments:
            print(f"  {a['seat']}号 {a['persona_id']} -> {a['model']} ({a['basis']})")
    else:
        seats = _mock_seats()
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
        await _finish(run, store, args, mid)
        if trace is not None:
            trace.close()
    return code


def _live(ev: Event) -> None:
    line = present(ev)
    if line is not None:
        print(line.text)


async def _finish(run: MatchRun, store: Store, args: argparse.Namespace, mid: int) -> None:
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

    out = Path(args.out) if args.out else Path(f"exports/match-{mid}-{args.view}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    events = await store.load_events(mid)
    seats = await store.load_seats(mid)
    doc = build_export(match_id=mid, match_info=m or {}, seats=seats,
                       events=events, usage=usage, view=args.view)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"导出：{out}")
    await store.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))