"""警长竞选流程位置测试（TDD RED 先行）。

验证标准局中警长竞选应该在：
- 第一天白天发言后（day_speech 之后）
- 放逐投票前（day_vote 之前）

而不是在第一夜夜间末尾（witch_turn / seer_check 之后）。
"""

import pytest

from app.engine.runner import MatchRunner
from app.games.registry import resolve_board
from app.games.werewolf.definition import WerewolfGame
from app.llm.gateway import MockLLM
from app.storage.repo import SqliteMatchRepository


def _seat_meta(roles: dict[int, str]) -> dict[int, dict]:
    return {s: {"model": "mock", "style": "", "strategy": "", "role": r}
            for s, r in roles.items()}


@pytest.fixture()
async def repo(tmp_path):
    r = SqliteMatchRepository(db_path=str(tmp_path / "ww.db"))
    await r.init()
    yield r
    await r.close()


class TestSheriffElectFlow:
    """警长竞选应在标准流程位置（day_speech 后、day_vote 前），不在夜间。"""

    async def test_standard9_警长竞选在白天发言后放逐投票前(self, repo):
        """标准 9 人局：警长竞选事件应该出现在 day_speech 与 day_vote 之间。

        当前 bug：警长竞选在夜间执行（witch_turn 后、night_resolve 前），
        应该在白天发言后、放逐投票前执行。
        """
        game, spec = resolve_board({"id": "p9-standard"})
        seats = [{"seat": i, "name": f"p{i}", "persona_id": "calm", "base_url": "",
                  "api_key_env": "", "model": "mock", "role": ""} for i in range(1, 10)]
        m = await repo.create_match(game_type="werewolf", ruleset="standard-9",
                                    board={"id": "p9-standard"}, rng_seed=42, seats=seats)
        roles = {a.seat: a.role for a in game.deal(spec, __import__("random").Random(42))}
        llm = MockLLM(script=[], fail_rate=0.0)
        runner = MatchRunner(match_id=m["id"], game=game, spec=spec, repo=repo,
                             gateway=llm, seed=42, seat_meta=_seat_meta(roles))
        result = await runner.run()
        assert result is not None

        events = await repo.list_events(m["id"], after_seq=0, view="god")

        # 找到所有关键阶段的位置（首次出现）
        phase_positions = []
        for i, e in enumerate(events):
            if e.type == "phase.started":
                phase = e.payload.get("phase", "")
                if phase in ("day_speech", "day_vote", "sheriff_elect"):
                    phase_positions.append((i, phase))

        # 验证：sheriff_elect 必须在 day_speech 后、day_vote 前
        day_speech_pos = None
        sheriff_elect_pos = None
        day_vote_pos = None

        for i, phase in phase_positions:
            if phase == "day_speech" and day_speech_pos is None:
                day_speech_pos = i
            elif phase == "sheriff_elect" and sheriff_elect_pos is None:
                sheriff_elect_pos = i
            elif phase == "day_vote" and day_vote_pos is None:
                day_vote_pos = i

        # 必须有这三个阶段
        assert day_speech_pos is not None, "缺少 day_speech 阶段"
        assert sheriff_elect_pos is not None, "缺少 sheriff_elect 阶段"
        assert day_vote_pos is not None, "缺少 day_vote 阶段"

        # 核心断言：警长竞选必须在 day_speech 之后
        assert sheriff_elect_pos > day_speech_pos, (
            f"警长竞选应在白天发言后，但实际位置: "
            f"day_speech={day_speech_pos}, sheriff_elect={sheriff_elect_pos}"
        )

        # 核心断言：警长竞选必须在 day_vote 之前
        assert sheriff_elect_pos < day_vote_pos, (
            f"警长竞选应在放逐投票前，但实际位置: "
            f"sheriff_elect={sheriff_elect_pos}, day_vote={day_vote_pos}"
        )

    async def test_standard9_警长竞选不在夜间(self, repo):
        """标准 9 人局：警长竞选不应该在夜间执行（witch_turn 和 night_resolve 之间）。"""
        game, spec = resolve_board({"id": "p9-standard"})
        seats = [{"seat": i, "name": f"p{i}", "persona_id": "calm", "base_url": "",
                  "api_key_env": "", "model": "mock", "role": ""} for i in range(1, 10)]
        m = await repo.create_match(game_type="werewolf", ruleset="standard-9",
                                    board={"id": "p9-standard"}, rng_seed=42, seats=seats)
        roles = {a.seat: a.role for a in game.deal(spec, __import__("random").Random(42))}
        llm = MockLLM(script=[], fail_rate=0.0)
        runner = MatchRunner(match_id=m["id"], game=game, spec=spec, repo=repo,
                             gateway=llm, seed=42, seat_meta=_seat_meta(roles))
        result = await runner.run()
        assert result is not None

        events = await repo.list_events(m["id"], after_seq=0, view="god")

        # 找到所有阶段的位置
        phases = []
        for i, e in enumerate(events):
            if e.type == "phase.started":
                phase = e.payload.get("phase", "")
                phases.append((i, phase))

        # 检查：sheriff_elect 不能出现在 witch_turn 和 night_resolve 之间（第一夜）
        in_night = False
        sheriff_in_night = False

        for i, phase in phases:
            if phase == "witch_turn":
                in_night = True
            elif phase == "night_resolve":
                in_night = False
            elif phase == "sheriff_elect" and in_night:
                sheriff_in_night = True
                break

        assert not sheriff_in_night, (
            "警长竞选不应该在夜间执行（witch_turn 和 night_resolve 之间）"
        )
