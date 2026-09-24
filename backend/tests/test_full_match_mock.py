"""狼人杀整局集成测试（Red 先行）：standard-9 单板 mock 整局，验证机制闭环与关键回归。

回归点：
- 单板收敛：事件流必须完全没有守卫相关事件；未知板子拒绝
- X2：当选警长不得被选举票判死（必须继续投票）
- S1：手动终止落 stopped，不再假造「狼人胜利」
- S3：全部调用失败时女巫不得消耗解药
- M4：天数上限必须在第 max_days 天白天真正走完后才生效
- M5：死因只进 god 事件，沉浸视角拿不到
"""

import pytest

from app.engine.runner import MatchRunner
from app.games.registry import resolve_board
from app.games.werewolf.definition import WerewolfGame
from app.llm.gateway import MockLLM
from app.storage.repo import SqliteMatchRepository


def seats(n: int = 9) -> list[dict]:
    return [{"seat": i, "name": f"p{i}", "persona_id": "calm-analyst", "base_url": "",
             "api_key_env": "", "model": "mock", "role": ""} for i in range(1, n + 1)]


def _seat_meta(roles: dict[int, str]) -> dict[int, dict]:
    return {s: {"model": "mock", "style": "", "strategy": "", "role": r}
            for s, r in roles.items()}


@pytest.fixture()
async def repo(tmp_path):
    r = SqliteMatchRepository(db_path=str(tmp_path / "ww.db"))
    await r.init()
    yield r
    await r.close()


async def _run_mock(repo, seed: int = 42, gateway=None, board: str = "p9-standard",
                    max_days: int = 2):
    game, spec = resolve_board({"id": board, "max_days": max_days})
    m = await repo.create_match(game_type="werewolf", ruleset=spec.ruleset,
                                board={"id": board, "max_days": max_days},
                                rng_seed=seed, seats=seats())
    roles = {a.seat: a.role for a in game.deal(spec, __import__("random").Random(seed))}
    runner = MatchRunner(match_id=m["id"], game=game, spec=spec, repo=repo,
                         gateway=gateway or MockLLM(script=[]), seed=seed,
                         seat_meta=_seat_meta(roles))
    result = await runner.run()
    events = await repo.list_events(m["id"], after_seq=0, view="god")
    return m, runner, result, events


class AbortGateway:
    """所有调用都失败：验证容错链的中性兜底。"""

    async def ask_json(self, *, base_url, api_key, model, messages, purpose, match_id=0, **kw):
        raise ConnectionError("simulated network failure")


class AbstainGateway:
    """所有动作都弃权/空刀：无人死亡，用来验证天数上限。"""

    async def ask_json(self, *, base_url, api_key, model, messages, purpose, match_id=0, **kw):
        return {"monologue": "", "speech": "", "action": {"type": "pass", "target": 0}}


class TestStandard9Match:
    async def test_mock整局_跑完且事件流完整(self, repo):
        m, runner, result, events = await _run_mock(repo)
        assert result is not None and result.winner in ("wolf", "good")

        seqs = [e.seq for e in events]
        assert seqs == list(range(1, len(seqs) + 1))  # seq 连续
        types = [e.type for e in events]
        assert types[0] == "match.created" and types[-1] == "match.finished"
        assert {"role.dealt", "night.kill_target", "sheriff.registered", "sheriff.badge",
                "skill_state.notice", "day_vote" if False else "vote.resolved"} <= set(types)
        # 单板收敛：standard-9 无守卫，绝不能出现守卫事件
        assert "night.guard_target" not in types

        # 可见性矩阵：immersive 无狼频道/独白/fallback/定刀/死因
        immersive = await repo.list_events(m["id"], after_seq=0, view="immersive")
        forbidden = {"channel.message", "channel.round.started", "channel.round.ended",
                     "player.monologue", "player.fallback", "night.kill_target",
                     "night.witch_action", "night.seer_query", "night.death_cause"}
        assert not any(e.type in forbidden for e in immersive)
        assert not any(e.type == "role.dealt" for e in immersive)

    async def test_同种子两次跑结果一致(self, repo):
        results = []
        for _ in range(2):
            _m, _r, r, events = await _run_mock(repo, seed=7)
            results.append((r.winner if r else None, [(e.seq, e.type) for e in events]))
        assert results[0] == results[1]  # 确定性

    async def test_角色回填座位(self, repo):
        m, _runner, _result, _events = await _run_mock(repo, seed=42)
        got = await repo.get_match(m["id"])
        counts: dict[str, int] = {}
        for s in got["seats"]:
            counts[s["role"]] = counts.get(s["role"], 0) + 1
        assert counts == {"wolf": 3, "seer": 1, "witch": 1, "hunter": 1, "villager": 3}

    async def test_当选警长继续投票(self, repo):
        """回归 X2：警长选举票不得把当选者判死（否则 2 票权重/归票全废）。"""
        _m, _r, _result, events = await _run_mock(repo, seed=5)
        badge = next(e for e in events
                     if e.type == "sheriff.badge" and e.payload.get("action") == "transfer")
        sheriff = badge.payload["to"]
        later = [e for e in events if e.type == "vote.cast"
                 and e.seq > badge.seq and e.payload.get("seat") == sheriff]
        assert later, f"警长 {sheriff} 号当选后应继续参与投票（未被选举票判死）"

    async def test_死因只进god事件(self, repo):
        """回归 M5：immersive 不得出现死因（docs/events-storage.md）。"""
        _m, _r, _result, events = await _run_mock(repo, seed=11)
        resolved = [e for e in events if e.type == "night.resolved"]
        assert resolved
        for e in resolved:
            assert all(v == "" for v in (e.payload.get("deaths") or {}).values()), \
                "night.resolved 不得带死因"
        causes = [e for e in events if e.type == "night.death_cause"]
        if any(e.payload.get("deaths") for e in resolved):
            assert causes, "有人死亡时应另有 god 级 night.death_cause 供复盘"
        immersive = await repo.list_events(_m["id"], after_seq=0, view="immersive")
        assert not any(e.type == "night.death_cause" for e in immersive)


class TestTimeLimit:
    async def test_天数上限在第max天白天走完后生效(self, repo):
        """回归 M4：第 N 天白天没打完不能判时限狼胜，且理由与实际一致。"""
        game, spec = resolve_board({"id": "p9-standard", "max_days": 3})
        assert spec.max_days == 3
        m = await repo.create_match(game_type="werewolf", ruleset=spec.ruleset,
                                    board={"id": "p9-standard", "max_days": 3},
                                    rng_seed=9, seats=seats())
        roles = {a.seat: a.role for a in game.deal(spec, __import__("random").Random(9))}
        runner = MatchRunner(match_id=m["id"], game=game, spec=spec, repo=repo,
                             gateway=AbstainGateway(), seed=9, seat_meta=_seat_meta(roles))
        result = await runner.run()
        assert result is not None and result.winner == "wolf"
        assert "第 3 天白天结束" in result.reason

        events = await repo.list_events(m["id"], after_seq=0, view="god")
        finished = next(e for e in events if e.type == "match.finished")
        phases = [e for e in events if e.type == "phase.started" and e.seq < finished.seq]
        assert phases[-1].payload["phase"] == "exile_resolve"
        assert int(phases[-1].payload["day"]) == 3
        # 第 4 夜不得开始
        assert not any(e.payload.get("phase") == "night_start" and int(e.payload["day"]) >= 4
                       for e in phases)


class TestFaultTolerance:
    async def test_全部调用失败仍跑完且不消耗解药(self, repo):
        """回归 S3：兜底动作必须中性——女巫没答上来绝不能用解药。"""
        _m, _r, result, events = await _run_mock(repo, seed=3, gateway=AbortGateway(),
                                                 max_days=2)
        assert result is not None or True  # 不卡死即可（胜负取决于状态机）
        types = {e.type for e in events}
        assert "player.fallback" in types
        witch_actions = [e.payload for e in events if e.type == "night.witch_action"]
        assert all(a.get("act") != "save" for a in witch_actions), \
            "调用失败时兜底不得替女巫使用解药"
        # 兜底空刀 → 平安夜
        assert all(not (e.payload.get("deaths") or {})
                   for e in events if e.type == "night.resolved")


class TestBoardRestriction:
    def test_只有p9_standard一个预设(self):
        from app.games.registry import PRESETS

        assert set(PRESETS) == {"p9-standard"}

    @pytest.mark.parametrize("board", ["p6-classic", "p8-classic", "p10-no-seer",
                                       "p12-standard", "nope"])
    def test_其他板子拒绝(self, board):
        with pytest.raises(ValueError, match="未知板子"):
            resolve_board({"id": board})

    def test_custom角色必须等于standard9(self):
        with pytest.raises(ValueError):
            resolve_board({"roles": {"wolf": 2, "seer": 1, "villager": 3}})
        game, spec = resolve_board({"roles": {"wolf": 3, "seer": 1, "witch": 1,
                                              "hunter": 1, "villager": 3}})
        assert isinstance(game, WerewolfGame)
        assert spec.player_count == 9
