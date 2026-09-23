"""命令行跑一局：--mock 用 MockLLM 确定性整局；不带 --mock 走真实 API（e2e 用）。

用法：
    python scripts/run_match.py --mock --board p6-classic --seed 42
    python scripts/run_match.py --board p12-standard   # 需配置座位接入与 key 环境变量
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.engine.runner import MatchRunner  # noqa: E402
from app.games.registry import PRESETS, resolve_board  # noqa: E402
from app.llm.gateway import MockLLM  # noqa: E402
from app.storage.repo import SqliteMatchRepository  # noqa: E402


async def run_mock(board_id: str, seed: int, n_players: int) -> int:
    game, spec = resolve_board({"id": board_id})
    repo = SqliteMatchRepository()
    await repo.init()
    seats = [{"seat": i, "name": f"AI-{i}", "persona_id": "calm-analyst",
              "base_url": "", "api_key_env": "", "model": "mock", "role": ""}
             for i in range(1, spec.player_count + 1)]
    m = await repo.create_match(game_type="werewolf", ruleset=spec.ruleset,
                                board={"id": board_id, "roles": spec.roles},
                                rng_seed=seed, seats=seats)
    roles = {a.seat: a.role for a in game.deal(spec, __import__("random").Random(seed))}
    seat_meta = {s: {"model": "mock", "style": "", "strategy": "", "role": r}
                 for s, r in roles.items()}
    llm = MockLLM(script=[], fail_rate=0.0)
    runner = MatchRunner(match_id=m["id"], game=game, spec=spec, repo=repo,
                         gateway=llm, seed=seed, seat_meta=seat_meta)
    result = await runner.run()
    events = await repo.list_events(m["id"], after_seq=0, view="god")
    seqs = [e.seq for e in events]
    ok_seq = seqs == list(range(1, len(seqs) + 1))
    print(json.dumps({
        "match_id": m["id"], "board": board_id, "seed": seed,
        "winner": result.winner if result else None,
        "reason": result.reason if result else None,
        "events": len(events), "seq_continuous": ok_seq,
    }, ensure_ascii=False, indent=2))
    await repo.close()
    return 0 if (result and ok_seq) else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="跑一局狼人杀")
    ap.add_argument("--mock", action="store_true", help="MockLLM 确定性跑局")
    ap.add_argument("--board", default="p6-classic", choices=sorted(PRESETS))
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    if args.mock:
        return asyncio.run(run_mock(args.board, args.seed, 0))
    print("真实 API 跑局请用 scripts/e2e_real.py（需要配置 providers 与 key）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
