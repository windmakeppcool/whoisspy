"""真实 LLM 跑一局（e2e）：读 backend/data 配置 + app/config/.env，全座位同一 provider。

用法：
    python scripts/e2e_real.py                     # p6-classic，provider 取 providers.json 首个非 mock
    python scripts/e2e_real.py --board p9-standard
    python scripts/e2e_real.py --provider mimo --model mimo-v2.6-flash
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.loader import (  # noqa: E402
    DEFAULT_ENV_FILE,
    load_config,
    load_env_file,
    parse_env_file,
)
from app.engine.runner import MatchRunner  # noqa: E402
from app.games.registry import PRESETS, resolve_board  # noqa: E402
from app.llm.gateway import OpenAICompatGateway  # noqa: E402
from app.scripts_helpers.e2e import build_real_seats, pick_provider  # noqa: E402
from app.storage.repo import SqliteMatchRepository, SqliteUsageRepository  # noqa: E402


async def run_real(board_id: str, provider_id: str = "", model_id: str = "") -> int:
    load_env_file()  # 注入 app/config/.env（不覆盖已有环境变量）
    bundle = load_config()  # backend/data/*.json，缺省回落内置
    providers = bundle.providers
    if provider_id:
        providers = [p for p in providers if p["id"] == provider_id] or providers
    provider, model = pick_provider(providers)
    if model_id:
        model = model_id
    print(f"provider={provider['id']} model={model} board={board_id}")
    game, spec = resolve_board({"id": board_id})
    env = parse_env_file(DEFAULT_ENV_FILE)
    import os

    env = {**env, **{k: v for k, v in os.environ.items() if k in env}}
    seats = build_real_seats(provider, model, n_players=spec.player_count, env=env,
                             personas=bundle.personas, providers=bundle.providers)
    if provider["id"] == "mock":
        print("警告：没有可用真实 provider（providers.json 只有 mock），将走 mock 启发式局")
    print(f"座位数：{spec.player_count}（{board_id}）")
    repo = SqliteMatchRepository()
    usage_repo = SqliteUsageRepository()
    await repo.init()
    await usage_repo.init()
    m = await repo.create_match(
        game_type="werewolf", ruleset=spec.ruleset,
        board={"id": board_id, "roles": spec.roles}, rng_seed=42, seats=seats)
    roles = {a.seat: a.role for a in game.deal(spec, __import__("random").Random(42))}
    seat_meta = {s: {"model": model, "base_url": provider.get("base_url", ""),
                     "api_key_env": provider.get("api_key_env", ""),
                     "api_key": os.environ.get(provider.get("api_key_env", ""), ""),
                     "style": "", "strategy": "", "role": r}
                 for s, r in roles.items()}
    gw = OpenAICompatGateway(usage_sink=_make_sink(usage_repo, m["id"]))
    runner = MatchRunner(match_id=m["id"], game=game, spec=spec, repo=repo,
                         gateway=gw, seed=42, seat_meta=seat_meta)
    result = await runner.run()
    usage = await usage_repo.summarize(m["id"])
    print(json.dumps({
        "match_id": m["id"], "board": board_id, "provider": provider["id"], "model": model,
        "winner": result.winner if result else None,
        "reason": result.reason if result else None,
        "usage": usage,
    }, ensure_ascii=False, indent=2))
    await repo.close()
    await usage_repo.close()
    return 0 if result else 1


def _make_sink(usage_repo: SqliteUsageRepository, match_id: int):
    class _Sink:
        async def record_call(self, **kw):
            await usage_repo.record_call(match_id=match_id,
                                         **{k: v for k, v in kw.items() if k != "match_id"})
    return _Sink()


def main() -> int:
    ap = argparse.ArgumentParser(description="真实 LLM 跑一局狼人杀")
    ap.add_argument("--board", default="p6-classic", choices=sorted(PRESETS))
    ap.add_argument("--provider", default="", help="provider id（默认取首个非 mock）")
    ap.add_argument("--model", default="", help="模型 id（默认取 provider 首个模型）")
    args = ap.parse_args()
    return asyncio.run(run_real(args.board, args.provider, args.model))


if __name__ == "__main__":
    raise SystemExit(main())
