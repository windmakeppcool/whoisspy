"""狼人杀整局集成测试（Red 先行）：mock 驱动 minimal 6 人局跑完，验证机制闭环。"""

import pytest

from app.engine.runner import MatchRunner
from app.games.registry import resolve_board
from app.games.werewolf.definition import WerewolfGame
from app.llm.gateway import MockLLM
from app.storage.repo import SqliteMatchRepository

SEATS = [{"seat": i, "name": f"p{i}", "persona_id": "calm", "base_url": "",
          "api_key_env": "", "model": "mock", "role": ""} for i in range(1, 7)]


def _seat_meta(roles: dict[int, str]) -> dict[int, dict]:
    return {s: {"model": "mock", "style": "", "strategy": "", "role": r}
            for s, r in roles.items()}


@pytest.fixture()
async def repo(tmp_path):
    r = SqliteMatchRepository(db_path=str(tmp_path / "ww.db"))
    await r.init()
    yield r
    await r.close()


class TestWerewolfFullMatch:
    async def test_mock整局_跑完且事件流完整(self, repo):
        game, spec = resolve_board({"id": "p6-classic"})
        m = await repo.create_match(game_type="werewolf", ruleset="minimal",
                                    board={"id": "p6-classic"}, rng_seed=42, seats=SEATS)
        roles = {s: r.role for s, r in
                 [(a.seat, a) for a in game.deal(spec, __import__("random").Random(42))]}
        llm = MockLLM(script=[], fail_rate=0.0)  # 全部走兜底/沉默也能跑完
        runner = MatchRunner(match_id=m["id"], game=game, spec=spec, repo=repo,
                             gateway=llm, seed=42, seat_meta=_seat_meta(roles))
        result = await runner.run()
        assert result is not None
        assert result.winner in ("wolf", "good")

        events = await repo.list_events(m["id"], after_seq=0, view="god")
        seqs = [e.seq for e in events]
        assert seqs == list(range(1, len(seqs) + 1))  # seq 连续
        types = [e.type for e in events]
        assert types[0] == "match.started" and types[-1] == "match.finished"
        assert "role.dealt" in types and "night.kill_target" in types

        # 可见性矩阵：god 全量，immersive 无狼频道/独白/fallback
        immersive = await repo.list_events(m["id"], after_seq=0, view="immersive")
        forbidden = {"channel.message", "channel.round.started", "channel.round.ended",
                     "player.monologue", "player.fallback", "night.kill_target",
                     "night.guard_target", "night.witch_action", "night.seer_query"}
        assert not any(e.type in forbidden for e in immersive)
        # role.dealt 沉浸视角也不可见（v1 观众无座位）
        assert not any(e.type == "role.dealt" for e in immersive)

    async def test_同种子两次跑结果一致(self, repo):
        results = []
        for _ in range(2):
            game, spec = resolve_board({"id": "p6-classic"})
            m = await repo.create_match(game_type="werewolf", ruleset="minimal",
                                        board={"id": "p6-classic"}, rng_seed=7, seats=SEATS)
            roles = {a.seat: a.role for a in game.deal(spec, __import__("random").Random(7))}
            llm = MockLLM(script=[], fail_rate=0.0)
            runner = MatchRunner(match_id=m["id"], game=game, spec=spec, repo=repo,
                                 gateway=llm, seed=7, seat_meta=_seat_meta(roles))
            r = await runner.run()
            events = await repo.list_events(m["id"], after_seq=0, view="god")
            results.append((r.winner if r else None, [(e.seq, e.type) for e in events]))
        assert results[0] == results[1]  # 确定性

    async def test_角色回填座位(self, repo):
        game, spec = resolve_board({"id": "p6-classic"})
        m = await repo.create_match(game_type="werewolf", ruleset="minimal",
                                    board={"id": "p6-classic"}, rng_seed=42, seats=SEATS)
        roles = {a.seat: a.role for a in game.deal(spec, __import__("random").Random(42))}
        llm = MockLLM(script=[], fail_rate=0.0)
        runner = MatchRunner(match_id=m["id"], game=game, spec=spec, repo=repo,
                             gateway=llm, seed=42, seat_meta=_seat_meta(roles))
        await runner.run()
        got = await repo.get_match(m["id"])
        wolf_count = sum(1 for s in got["seats"] if s["role"] == "wolf")
        seer_count = sum(1 for s in got["seats"] if s["role"] == "seer")
        assert (wolf_count, seer_count) == (2, 1)
