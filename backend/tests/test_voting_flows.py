"""投票/发言流程测试（Red 先行）：

- X1：警长首轮平票走 PK 时不得崩溃（回归 `_speech_round` 缺 step 参数）
- M2：放逐投票平票必须走 PK（平票者发言 + 其余全体重投），再平票才平安日
- M3：白天发言定序——有警长由警长指定首位；无警长 rng 随机起始
"""

import re
from random import Random

import pytest

from app.engine.runner import MatchRunner
from app.games.registry import resolve_board
from app.storage.repo import SqliteMatchRepository


def _seat_of(prompt: str) -> int:
    m = re.search(r"你是 (\d+) 号座位", prompt)
    return int(m.group(1)) if m else 0


def _seats(n: int = 9) -> list[dict]:
    return [{"seat": i, "name": f"p{i}", "persona_id": "calm-analyst", "base_url": "",
             "api_key_env": "", "model": "mock", "role": ""} for i in range(1, n + 1)]


@pytest.fixture()
async def repo(tmp_path):
    r = SqliteMatchRepository(db_path=str(tmp_path / "v.db"))
    await r.init()
    yield r
    await r.close()


class ScriptedGateway:
    """按 purpose/prompt 决定回复；记录每次调用，便于断言流程。

    默认空刀 + 全员弃权，保证流程可控（夜里不死人、放逐靠脚本制造平票）。
    """

    def __init__(self, register: tuple[int, ...] = (1,), day_vote: dict | None = None,
                 sheriff_vote: dict | None = None):
        self.register = set(register)
        self.day_vote = day_vote or {}
        self.sheriff_vote = sheriff_vote or {}
        self.calls: list[tuple[str, int, str]] = []

    async def ask_json(self, *, base_url, api_key, model, messages, purpose, match_id=0, **kw):
        prompt = messages[0]["content"]
        seat = _seat_of(prompt)
        pk = "PK" in prompt
        self.calls.append((purpose, seat, "PK" if pk else ""))
        if purpose == "sheriff_register":
            return {"monologue": "", "speech": "",
                    "action": {"type": "register", "yes": seat in self.register}}
        if purpose == "sheriff_vote":
            target = self.sheriff_vote.get("PK" if pk else "first", {}).get(seat, 1)
            return {"monologue": "", "speech": "", "action": {"type": "vote", "target": target}}
        if purpose == "speech_order":
            return {"monologue": "", "speech": "",
                    "action": {"type": "speech_order", "target": 2}}
        if purpose == "closing":
            return {"monologue": "", "speech": "", "action": {"type": "kill", "target": 0}}
        if purpose == "check":
            return {"monologue": "", "speech": "", "action": {"type": "check", "target": 0}}
        if purpose == "witch_turn":
            return {"monologue": "", "speech": "", "action": {"type": "pass", "target": 0}}
        if purpose in ("vote",):
            key = "PK" if pk else "first"
            target = self.day_vote.get(key, {}).get(seat, 0)
            return {"monologue": "", "speech": "",
                    "action": {"type": "vote", "target": target}}
        if purpose == "last_words":
            return {"monologue": "", "speech": "遗言", "action": {"type": "speech", "target": 0}}
        # 发言类（day_speech / sheriff_speech / pk_speech / wolf_channel）
        return {"monologue": "", "speech": f"{seat}号发言", "action": {"type": "speech", "target": 0}}


async def _run(repo, gateway, seed: int = 1, max_days: int = 2):
    game, spec = resolve_board({"id": "p9-standard", "max_days": max_days})
    m = await repo.create_match(game_type="werewolf", ruleset=spec.ruleset,
                                board={"id": "p9-standard", "max_days": max_days},
                                rng_seed=seed, seats=_seats())
    roles = {a.seat: a.role for a in game.deal(spec, Random(seed))}
    runner = MatchRunner(match_id=m["id"], game=game, spec=spec, repo=repo,
                         gateway=gateway, seed=seed,
                         seat_meta={s: {"model": "mock", "role": r} for s, r in roles.items()})
    result = await runner.run()
    events = await repo.list_events(m["id"], after_seq=0, view="god")
    return result, events


class TestSheriffPk:
    """X1 回归：警长首轮平票 → PK 发言 → 重投，全程不得抛异常。"""

    async def test_首轮平票走PK不崩溃(self, repo):
        # 1/2/3 上警，未上警的 4..9 号 3:3 投 1/2 → 平票
        gw = ScriptedGateway(register=(1, 2, 3),
                             sheriff_vote={"first": {4: 1, 5: 1, 6: 1, 7: 2, 8: 2, 9: 2},
                                           "PK": {4: 1, 5: 1, 6: 1, 7: 2, 8: 2, 9: 2}})
        result, events = await _run(repo, gw)
        titles = [e.payload.get("title") for e in events if e.type == "vote.resolved"]
        assert "警长投票" in titles
        assert "警长 PK 投票" in titles, "首轮平票必须进入 PK 重投"
        # PK 发言（平票者的竞选宣言）确实发生了
        assert any(p == "sheriff_speech" for p, _s, _k in gw.calls)
        # 走到正常结束（不抛异常、有 match.finished）
        assert result is not None
        assert any(e.type == "match.finished" for e in events)

    async def test_首轮全员弃权_警徽丢失不崩溃(self, repo):
        gw = ScriptedGateway(register=(1,))
        _result, events = await _run(repo, gw)
        badges = [e.payload for e in events if e.type == "sheriff.badge"]
        # 恰 1 人上警 → 自动当选
        assert badges and badges[0]["action"] == "transfer"

    async def test_PK重投排除平票者(self, repo):
        """PK 轮投票人不含平票者本人（docs/games/werewolf.md:108）。"""
        gw = ScriptedGateway(register=(1, 2, 3),
                             sheriff_vote={"first": {4: 1, 5: 1, 6: 1, 7: 2, 8: 2, 9: 2},
                                           "PK": {4: 1, 5: 1, 6: 1, 7: 2, 8: 2, 9: 2}})
        await _run(repo, gw)
        pk_voters = sorted(s for p, s, k in gw.calls
                           if p == "sheriff_vote" and k == "PK")
        # 首轮平票 1/2 号 → PK 投票人应为 3..9（含已上警的 3 号，排除 1、2）
        assert pk_voters, "PK 重投必须发生"
        assert 1 not in pk_voters and 2 not in pk_voters
        assert 3 in pk_voters


class TestDayPk:
    """M2：放逐平票 → PK（平票者发言 + 其余全体重投）→ 仍平票平安日。"""

    async def test_放逐平票走PK再平票平安日(self, repo):
        # 警长 = 3 号（不参与首轮投票构造）；1 号投 2 号、2 号投 1 号 → 平票
        # PK 轮全体弃权 → 平安日
        gw = ScriptedGateway(register=(3,),
                             day_vote={"first": {1: 2, 2: 1}, "PK": {}})
        result, events = await _run(repo, gw)

        titles = [e.payload.get("title") for e in events if e.type == "vote.resolved"]
        assert "放逐 PK 投票" in titles, "放逐平票必须进入 PK"
        assert all(e.payload.get("scope") == "exile" for e in events
                   if e.type == "vote.resolved")
        # PK 发言确实发生（平票者 1、2 号；对局跑满两天 → 每天各一次）
        pk_speakers = sorted({s for p, s, _k in gw.calls if p == "pk_speech"})
        assert pk_speakers == [1, 2]
        # 再平票 → 平安日：无人被放逐、无遗言
        assert not any(e.type == "player.last_words" for e in events)
        final = [e for e in events if e.type == "vote.resolved"
                 and e.payload.get("title") == "放逐 PK 投票"]
        assert all(e.payload.get("exiled") is None for e in final)
        assert result is not None

    async def test_放逐无人投票不触发PK(self, repo):
        """全员弃权（无并列席位）不该走 PK——没有平票者可言。"""
        gw = ScriptedGateway(register=(3,), day_vote={"first": {}, "PK": {}})
        _result, events = await _run(repo, gw)
        titles = [e.payload.get("title") for e in events if e.type == "vote.resolved"]
        assert "放逐 PK 投票" not in titles

    async def test_放逐PK后重投成功放逐(self, repo):
        """PK 轮投出结果 → 正常放逐（遗言链触发）。"""
        gw = ScriptedGateway(register=(3,),
                             day_vote={"first": {1: 2, 2: 1}, "PK": {3: 1}})
        _result, events = await _run(repo, gw)
        exiled = [e.payload.get("exiled") for e in events
                  if e.type == "vote.resolved"
                  and e.payload.get("title") == "放逐 PK 投票"]
        assert exiled and exiled[0] == 1
        assert any(e.type == "player.last_words" for e in events)


class TestSpeechOrder:
    """M3：发言定序（有警长由警长指定首位；无警长 rng 随机起始）。"""

    async def test_有警长由警长定序(self, repo):
        gw = ScriptedGateway(register=(1,))  # 1 号自动当选警长，脚本指定首位 = 2 号
        _result, events = await _run(repo, gw)
        orders = [e.payload for e in events if e.type == "day.speech_order"]
        assert orders, "每个白天都应有发言定序事件"
        first = orders[0]
        assert first["decided_by"] == "sheriff"
        assert first["start"] == 2
        assert first["order"][0] == 2
        # 按座位升序环绕
        assert first["order"] == [2, 3, 4, 5, 6, 7, 8, 9, 1]
        # 实际发言顺序与定序一致
        speeches = [e.payload["seat"] for e in events if e.type == "player.speech"
                    and e.phase == "day_speech"]
        assert speeches[: len(first["order"])] == first["order"]

    async def test_无警长由rng随机起始(self, repo):
        gw = ScriptedGateway(register=())  # 无人上警 → 警徽丢失
        _result, events = await _run(repo, gw)
        orders = [e.payload for e in events if e.type == "day.speech_order"]
        assert orders
        assert all(o["decided_by"] == "rng" for o in orders)
        for o in orders:
            assert sorted(o["order"]) == list(range(1, 10))
            assert o["order"][0] == o["start"]

    async def test_定序事件公开可见(self, repo):
        gw = ScriptedGateway(register=(1,))
        _result, events = await _run(repo, gw)
        immersive = await repo.list_events(1, after_seq=0, view="immersive")
        order_ev = next(e for e in events if e.type == "day.speech_order")
        assert order_ev.vis.level == "public"
        assert any(e.type == "day.speech_order" for e in immersive)
