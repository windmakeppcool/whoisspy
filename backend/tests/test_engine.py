"""引擎测试（Red 先行）：faults 兜底、Step 执行、MatchRunner mock 整局（seq 连续/可见性/胜负落账）。"""

import asyncio
import json

import pytest

from app.core import ActionRequest, Event, VisMeta
from app.games.base import GameState, Step
from app.engine.faults import fallback_action
from app.engine.runner import MatchRunner
from app.llm.gateway import MockLLM
from app.storage.repo import SqliteMatchRepository


# ---------- 兜底 ----------

class TestFallback:
    def test_投票兜底弃权(self):
        a = fallback_action(ActionRequest(action_type="vote", candidates=[1, 2]))
        assert a == {"type": "vote", "target": 0}

    def test_定刀兜底空刀(self):
        a = fallback_action(ActionRequest(action_type="kill", candidates=[1, 2]))
        assert a == {"type": "kill", "target": 0}

    def test_验人兜底no_result(self):
        a = fallback_action(ActionRequest(action_type="check", candidates=[1, 2]))
        assert a == {"type": "check", "target": 0}

    def test_发言兜底沉默(self):
        a = fallback_action(ActionRequest(action_type="speech"))
        assert a == {"type": "speech", "target": 0}


# ---------- Runner 整局 ----------

SEATS = [{"seat": i, "name": f"p{i}", "persona_id": "calm", "base_url": "",
          "api_key_env": "", "model": "mock", "role": ""} for i in range(1, 7)]

SEAT_META = {i: {"model": "mock", "style": "", "strategy": "", "role": "villager"}
             for i in range(1, 7)}


def _scripted_speech(seat: int, text: str, target: int | None = None) -> dict:
    action = {"type": "vote", "target": target} if target else None
    return {"monologue": f"{seat}号内心", "speech": text, "action": action}


class FakeGame:
    """最小假游戏：3 个白天发言 + 投票即结束（好人胜），验证 runner 机制而非游戏规则。"""

    game_type = "fake"

    def __init__(self):
        self.roles = {i: "villager" for i in range(1, 7)}
        self.alive = {i: True for i in range(1, 7)}

    def validate_board(self, cfg):
        from app.core import BoardSpec
        return BoardSpec(game_type="fake", ruleset="test", roles={"villager": 6})

    def deal(self, spec, rng):
        from app.core import RoleAssignment
        return [RoleAssignment(seat=i, role="villager") for i in range(1, 7)]

    def initial_state(self, spec, roles):
        st = GameState(spec=spec, roles={r.seat: r.role for r in roles},
                       alive={r.seat: True for r in roles})
        return st

    def next_step(self, state):
        if not state.extra.get("spoke"):
            return Step(kind="serial_speech", params={"speakers": [1, 2], "purpose": "speech"})
        if not state.extra.get("voted"):
            return Step(kind="ballot", params={"voters": [1, 2], "purpose": "vote"})
        from app.core import GameResult
        state.winner = GameResult(winner="good", reason="测试结束")
        return Step(kind="noop", params={})

    def apply(self, state, event):
        if event.type == "player.speech":
            state.extra["spoke"] = True
        if event.type == "vote.resolved":
            state.extra["voted"] = True

    def action_schema(self, state, step):
        if step.kind == "serial_speech":
            return ActionRequest(action_type="speech", prompt="请发言")
        if step.kind == "ballot":
            return ActionRequest(action_type="vote", candidates=[1, 2], prompt="请投票")
        return None

    def validate_action(self, state, step, seat, action):
        return action

    def neutral_action(self, state, step):
        """中性兜底（引擎容错链用）：假游戏一律沉默/弃权。"""
        if step.kind == "ballot":
            return {"type": "vote", "target": 0}
        return {"type": "speech", "target": 0}

    async def play(self, ctx, step):
        """步内流程（游戏自己的规则）：engine 只提供 ctx 原语。"""
        if step.kind == "serial_speech":
            request = self.action_schema(ctx.state, step)
            for seat in step.params["speakers"]:
                if ctx.state.alive.get(seat):
                    await ctx.speech(seat, request,
                                     purpose=step.params.get("purpose", "speech"),
                                     step=step)
        elif step.kind == "ballot":
            votes = await ctx.collect_ballot(step.params["voters"], [1, 2],
                                             title="测试投票", step_kind="ballot",
                                             purpose=step.params.get("purpose", "vote"))
            tally: dict[int, int] = {}
            for target in votes.values():
                if target:
                    tally[target] = tally.get(target, 0) + 1
            top = max(tally.values()) if tally else 0
            leaders = sorted(t for t, c in tally.items() if c == top)
            exiled = leaders[0] if len(leaders) == 1 else None
            await ctx.emit("vote.resolved",
                           {"votes": votes, "title": "测试投票", "scope": "exile",
                            "exiled": exiled, "tie": len(leaders) != 1,
                            "tied": leaders})

    def memory_line(self, ev):
        return None

    def phase_day(self, state, step):
        return state.day

    def check_winner(self, state):
        return state.winner

    def visibility(self, event, state):
        if event.type == "player.monologue":
            return VisMeta(level="god")
        return VisMeta(level="public")

    def rule_slices(self):
        return {"overview": "假游戏规则"}

    def slices_for(self, step):
        return ["overview"]


FAKE_SPEC = FakeGame().validate_board({})  # spec 现在必填：假游戏也要给一份合法规格


@pytest.fixture()
async def repo(tmp_path):
    r = SqliteMatchRepository(db_path=str(tmp_path / "e.db"))
    await r.init()
    yield r
    await r.close()


class TestMatchRunner:
    async def test_mock整局_seq连续且落账完整(self, repo):
        m = await repo.create_match(game_type="fake", ruleset="minimal",
                                    board={"roles": {}}, rng_seed=1, seats=SEATS)
        script = ([_scripted_speech(1, "我先说"), _scripted_speech(2, "我后说")]
                  + [{"speech": "", "monologue": "", "action": {"type": "vote", "target": 2}},
                     {"speech": "", "monologue": "", "action": {"type": "vote", "target": 1}}])
        llm = MockLLM(script=script)
        runner = MatchRunner(match_id=m["id"], game=FakeGame(), spec=FAKE_SPEC,
                             repo=repo, gateway=llm, seed=1, seat_meta=dict(SEAT_META))
        result = await runner.run()
        assert result is not None and result.winner == "good"
        events = await repo.list_events(m["id"], after_seq=0, view="god")
        seqs = [e.seq for e in events]
        assert seqs == list(range(1, len(seqs) + 1))  # seq 连续无空洞
        types = [e.type for e in events]
        assert types[0] == "match.created"  # 创建事件 → 开跑 → 结束
        assert types[1] == "match.started"
        assert types[-1] == "match.finished"
        assert "player.speech" in types and "vote.resolved" in types

    async def test_可见性_monologue为god_发言为public(self, repo):
        m = await repo.create_match(game_type="fake", ruleset="minimal",
                                    board={"roles": {}}, rng_seed=1, seats=SEATS)
        script = [_scripted_speech(1, "发言"), _scripted_speech(2, "发言"),
                  {"speech": "", "monologue": "", "action": {"type": "vote", "target": 2}},
                  {"speech": "", "monologue": "", "action": {"type": "vote", "target": 1}}]
        llm = MockLLM(script=script)
        runner = MatchRunner(match_id=m["id"], game=FakeGame(), spec=FAKE_SPEC,
                             repo=repo, gateway=llm, seed=1, seat_meta=dict(SEAT_META))
        await runner.run()
        god = await repo.list_events(m["id"], after_seq=0, view="god")
        immersive = await repo.list_events(m["id"], after_seq=0, view="immersive")
        assert any(e.type == "player.monologue" for e in god)
        assert not any(e.type == "player.monologue" for e in immersive)
        assert any(e.type == "player.speech" for e in immersive)

    async def test_故障注入仍跑完并产生fallback(self, repo):
        m = await repo.create_match(game_type="fake", ruleset="minimal",
                                    board={"roles": {}}, rng_seed=1, seats=SEATS)
        # 剧本只给发言；投票阶段靠 MockLLM 坏 JSON → 修复失败 → 弃权兜底
        llm = MockLLM(script=[_scripted_speech(1, "a"), _scripted_speech(2, "b")],
                      fail_rate=1.0, rng_seed=5, fail_mode="bad_json")
        runner = MatchRunner(match_id=m["id"], game=FakeGame(), spec=FAKE_SPEC,
                             repo=repo, gateway=llm, seed=1, seat_meta=dict(SEAT_META))
        result = await runner.run()
        assert result is not None  # 不卡死，跑完全局
        events = await repo.list_events(m["id"], after_seq=0, view="god")
        assert any(e.type == "player.fallback" for e in events)

    async def test_角色回填与事件day_phase(self, repo):
        m = await repo.create_match(game_type="fake", ruleset="minimal",
                                    board={"roles": {}}, rng_seed=1, seats=SEATS)
        script = [_scripted_speech(1, "a"), _scripted_speech(2, "b"),
                  {"speech": "", "monologue": "", "action": {"type": "vote", "target": 2}},
                  {"speech": "", "monologue": "", "action": {"type": "vote", "target": 1}}]
        llm = MockLLM(script=script)
        runner = MatchRunner(match_id=m["id"], game=FakeGame(), spec=FAKE_SPEC,
                             repo=repo, gateway=llm, seed=1, seat_meta=dict(SEAT_META))
        await runner.run()
        got = await repo.get_match(m["id"])
        assert got["status"] == "finished"
        assert got["current_seq"] == len(await repo.list_events(m["id"], after_seq=0, view="god"))

    async def test_手动终止落stopped不假造胜负(self, repo):
        """回归 S1：stop 必须是 stopped，且不得写成「狼人胜利 + finished」。"""
        m = await repo.create_match(game_type="fake", ruleset="minimal",
                                    board={"roles": {}}, rng_seed=1, seats=SEATS)
        stop = asyncio.Event()
        stop.set()  # 开跑前就请求停止

        runner = MatchRunner(match_id=m["id"], game=FakeGame(), spec=FAKE_SPEC,
                             repo=repo, gateway=MockLLM(script=[]), seed=1,
                             seat_meta=dict(SEAT_META), stop_flag=stop)
        result = await runner.run()
        assert result is None  # 未分胜负

        got = await repo.get_match(m["id"])
        assert got["status"] == "stopped"
        assert got["result"]["winner"] is None
        assert "终止" in got["result"]["reason"]

        events = await repo.list_events(m["id"], after_seq=0, view="god")
        types = [e.type for e in events]
        assert "match.stopped" in types
        assert "match.finished" not in types  # 不得同时落 finished
        stopped = next(e for e in events if e.type == "match.stopped")
        assert stopped.payload.get("reason")

    async def test_started事件带真实种子(self, repo):
        """回归：match.started 记录的必须是可复现的 rng_seed，而不是随机浮点。"""
        m = await repo.create_match(game_type="fake", ruleset="minimal",
                                    board={"roles": {}}, rng_seed=123, seats=SEATS)
        runner = MatchRunner(match_id=m["id"], game=FakeGame(), spec=FAKE_SPEC,
                             repo=repo, gateway=MockLLM(script=[]), seed=123,
                             seat_meta=dict(SEAT_META))
        await runner.run()
        events = await repo.list_events(m["id"], after_seq=0, view="god")
        started = next(e for e in events if e.type == "match.started")
        assert started.payload.get("rng_seed") == 123
        assert not isinstance(started.payload.get("rng_seed"), float)
