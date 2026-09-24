"""警长竞选流程位置测试（用户拍板 D21：竞选在公布死讯前）。

验证标准局中警长竞选的时序（推翻 D20，回到 D14 原始顺序）：
- 第 1 天夜末执行（witch_turn 之后、night_resolve 之前）
- 即：警长竞选 → 公布死讯 → 白天发言 → 放逐投票
"""

import pytest

from app.engine.runner import MatchRunner
from app.games.registry import resolve_board
from app.llm.gateway import MockLLM
from app.storage.repo import SqliteMatchRepository


def _seat_meta(roles: dict[int, str]) -> dict[int, str]:
    return {s: {"model": "mock", "style": "", "strategy": "", "role": r}
            for s, r in roles.items()}


@pytest.fixture()
async def repo(tmp_path):
    r = SqliteMatchRepository(db_path=str(tmp_path / "ww.db"))
    await r.init()
    yield r
    await r.close()


async def _run_standard9(repo) -> list:
    game, spec = resolve_board({"id": "p9-standard"})
    seats = [{"seat": i, "name": f"p{i}", "persona_id": "calm", "base_url": "",
              "api_key_env": "", "model": "mock", "role": ""}
             for i in range(1, 10)]
    m = await repo.create_match(game_type="werewolf", ruleset="standard-9",
                                board={"id": "p9-standard"}, rng_seed=42, seats=seats)
    roles = {a.seat: a.role for a in game.deal(spec, __import__("random").Random(42))}
    llm = MockLLM(script=[], fail_rate=0.0)
    runner = MatchRunner(match_id=m["id"], game=game, spec=spec, repo=repo,
                         gateway=llm, seed=42, seat_meta=_seat_meta(roles))
    result = await runner.run()
    assert result is not None
    return await repo.list_events(m["id"], after_seq=0, view="god")


def _first_positions(events) -> dict[str, int]:
    """关键阶段首次出现的位置索引。"""
    positions: dict[str, int] = {}
    for i, e in enumerate(events):
        if e.type == "phase.started":
            phase = e.payload.get("phase", "")
            if phase in ("sheriff_elect", "night_resolve", "day_speech", "day_vote") \
                    and phase not in positions:
                positions[phase] = i
    return positions


class TestSheriffElectFlow:
    """警长竞选在公布死讯前（第 1 天夜末），随后死讯 → 发言 → 投票。"""

    async def test_standard9_警长竞选在死讯公布前(self, repo):
        """竞选（首次）必须早于 night_resolve（首次死讯公布）。"""
        events = await _run_standard9(repo)
        pos = _first_positions(events)
        assert "sheriff_elect" in pos, "缺少 sheriff_elect 阶段"
        assert "night_resolve" in pos, "缺少 night_resolve 阶段"
        assert "day_speech" in pos, "缺少 day_speech 阶段"
        assert "day_vote" in pos, "缺少 day_vote 阶段"

        # 核心：竞选在死讯公布前
        assert pos["sheriff_elect"] < pos["night_resolve"], (
            f"警长竞选应在公布死讯前，但实际位置: "
            f"sheriff_elect={pos['sheriff_elect']}, night_resolve={pos['night_resolve']}"
        )
        # 完整顺序：竞选 → 死讯 → 发言 → 投票
        assert pos["sheriff_elect"] < pos["night_resolve"] < pos["day_speech"] < pos["day_vote"], (
            f"顺序应为 竞选→死讯→发言→投票，实际: {pos}"
        )

    async def test_standard9_竞选在夜末_witch_turn之后(self, repo):
        """竞选发生在 witch_turn（最后一个夜行动）之后、night_resolve 之前。"""
        events = await _run_standard9(repo)
        phases: list[tuple[int, str]] = []
        for i, e in enumerate(events):
            if e.type == "phase.started":
                phases.append((i, e.payload.get("phase", "")))

        witch_pos = next((i for i, p in phases if p == "witch_turn"), None)
        elect_pos = next((i for i, p in phases if p == "sheriff_elect"), None)
        resolve_pos = next((i for i, p in phases if p == "night_resolve"), None)
        assert witch_pos is not None, "缺少 witch_turn 阶段"
        assert elect_pos is not None, "缺少 sheriff_elect 阶段"
        assert resolve_pos is not None, "缺少 night_resolve 阶段"

        assert witch_pos < elect_pos < resolve_pos, (
            f"夜末顺序应为 witch_turn→sheriff_elect→night_resolve，"
            f"实际: witch={witch_pos}, elect={elect_pos}, resolve={resolve_pos}"
        )

    async def test_standard9_投票前死讯与发言不重复(self, repo):
        """回滚 D20 的重复缺陷：第 1 天放逐投票前 night_resolve/day_speech 各只出现一次。

        D20 把竞选插在 day_speech 后，而 sheriff_elect 之后仍走
        night_resolve → day_speech 分支，导致死讯公布与白天发言各执行两遍。
        """
        events = await _run_standard9(repo)
        resolve_before_vote = 0
        speech_before_vote = 0
        for e in events:
            if e.type != "phase.started":
                continue
            phase = e.payload.get("phase", "")
            if phase == "day_vote":
                break
            if phase == "night_resolve":
                resolve_before_vote += 1
            elif phase == "day_speech":
                speech_before_vote += 1
        assert resolve_before_vote == 1, (
            f"投票前 night_resolve 应只出现 1 次，实际 {resolve_before_vote}")
        assert speech_before_vote == 1, (
            f"投票前 day_speech 应只出现 1 次，实际 {speech_before_vote}")
