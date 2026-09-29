"""export 测试（Red 先行）：docs/backend/11-export.md 第三/四节。"""

from app.events import Event, god, public, seat
from app.export import build_export


def _ev(seq, type_, payload=None, vis=None, day=1, phase="x"):
    return Event(seq=seq, type=type_, day_index=day, phase=phase,
                 payload=payload or {}, vis=vis or public())


def _sample_events():
    return [
        _ev(1, "match.created", {"seed": 42, "roles": {"wolf": 3}}, day=0, phase=""),
        _ev(2, "match.started", {"seed": 42}, day=0, phase=""),
        _ev(3, "role.dealt", {"seat": 1, "role": "wolf"}, vis=seat(1), day=0, phase=""),
        _ev(4, "phase.started", {"phase": "night_start", "day": 1, "label": "入夜"},
            phase="night_start"),
        _ev(5, "night.started", {"day": 1}, phase="night_start"),
        _ev(6, "channel.round.started", {"channel": "wolf", "members": [1]}, vis=god(),
            phase="wolf_meeting"),
        _ev(7, "channel.message", {"seat": 1, "text": "刀 5"}, vis=seat(1),
            phase="wolf_meeting"),
        _ev(8, "night.kill_target", {"target": 5, "decided_by": "majority"}, vis=god(),
            phase="wolf_meeting"),
        _ev(9, "night.resolved", {"day": 1, "deaths": {"5": ""}}, phase="night_resolve"),
        _ev(10, "night.death_cause", {"causes": {5: "knife"}}, vis=god(),
            phase="night_resolve"),
        _ev(11, "phase.started", {"phase": "sheriff_elect", "day": 1, "label": "警长竞选"},
            phase="sheriff_elect"),
        _ev(12, "sheriff.registered", {"seats": [1, 2]}, phase="sheriff_elect"),
        _ev(13, "sheriff.badge", {"action": "transfer", "to": 1}, phase="sheriff_elect"),
        _ev(14, "phase.started", {"phase": "speech_order", "day": 1, "label": "发言定序"},
            phase="speech_order"),
        _ev(15, "day.speech_order", {"order": [1, 2, 3], "start": 1, "decided_by": "rng"},
            phase="speech_order"),
        _ev(16, "player.speech", {"seat": 1, "text": "我是预言家"}, phase="day_speech"),
        _ev(17, "phase.started", {"phase": "day_vote", "day": 1, "label": "放逐投票"},
            phase="day_vote"),
        _ev(18, "vote.cast", {"seat": 1, "target": 2}, phase="day_vote"),
        _ev(19, "vote.resolved", {"votes": {1: 2}, "scope": "exile", "exiled": 2,
                                  "tie": False, "tied": []}, phase="day_vote"),
        _ev(20, "phase.started", {"phase": "exile_resolve", "day": 1, "label": "放逐结算"},
            phase="exile_resolve"),
        _ev(21, "player.fallback", {"seat": 3, "reason": "超时", "purpose": "vote"},
            vis=god(), phase="day_vote"),
        _ev(22, "rule.error", {"phase": "day_vote", "reason": "boom"}, vis=god(),
            phase="day_vote"),
        _ev(23, "match.finished", {"winner": "good", "reason": "狼人全部出局"},
            phase="exile_resolve"),
    ]


def _usage():
    return {"calls": 10, "prompt_tokens": 1000, "completion_tokens": 100,
            "cached_prompt_tokens": 500, "cost_micros": 123, "cache_hit_rate": 0.5}


def _match_info():
    return {"seed": 42, "status": "finished",
            "result": {"winner": "good", "reason": "狼人全部出局"},
            "board": {"roles": {"wolf": 3}, "wolf_meeting_rounds": 2, "max_days": 8,
                      "model_assignments": [{"seat": 1, "basis": "random"}]}}


def _seats():
    return [{"seat": 1, "persona_id": "p1", "model": "mock", "role": "wolf"},
            {"seat": 2, "persona_id": "p2", "model": "mock", "role": "seer"}]


def _export(view="god", personas=None):
    return build_export(match_id=1, match_info=_match_info(), seats=_seats(),
                        events=_sample_events(), usage=_usage(), view=view,
                        personas=personas)


# ---------- schema 与分段 ----------

def test_导出schema完整性():
    doc = _export()
    assert doc["match_id"] == 1
    assert doc["view"] == "god"
    assert "exported_at" in doc
    assert set(doc["match"]) == {"seed", "status", "winner", "reason",
                                 "board", "seats", "model_assignments"}
    assert doc["match"]["winner"] == "good"
    assert doc["match"]["seats"][0]["role"] == "wolf"  # god 视角带角色
    assert set(doc["usage"]) == {"calls", "prompt_tokens", "completion_tokens",
                                 "cached_prompt_tokens", "cost_micros",
                                 "cache_hit_rate", "fallbacks", "rule_errors"}


def test_分段开局夜昼():
    doc = _export()
    labels = [s["label"] for s in doc["segments"]]
    assert labels[0] == "开局"
    assert labels[1] == "第一夜"
    assert labels[2] == "第一天"
    # 警长竞选（夜末）归第一夜段，不放逐判死
    first_night = doc["segments"][1]
    texts = [e["text"] for e in first_night["entries"]]
    assert any("警长" in t for t in texts)
    assert any("狼队选择击杀" in t for t in texts)
    # 白天段有发言与放逐
    first_day = doc["segments"][2]
    texts = [e["text"] for e in first_day["entries"]]
    assert any("我是预言家" in t for t in texts)
    assert any("被放逐" in t for t in texts)


def test_分段entries保持事件序():
    doc = _export()
    day_seg = doc["segments"][2]
    kinds = [e["kind"] for e in day_seg["entries"]]
    assert kinds[0] == "phase"
    assert "speech" in kinds
    assert "vote" in kinds


def test_usage含兜底计数():
    doc = _export()
    assert doc["usage"]["fallbacks"] == 1  # player.fallback ×1
    assert doc["usage"]["rule_errors"] == 1  # rule.error ×1


# ---------- 视角过滤 ----------

def test_public视角过滤god与seat事件():
    doc = _export(view="public")
    texts = []
    for seg in doc["segments"]:
        texts += [e["text"] for e in seg["entries"]]
    joined = "\n".join(texts)
    assert "刀 5" not in joined  # channel.message（seat）不可见
    assert "狼队选择击杀" not in joined  # kill_target（god）不可见
    assert "死因" not in joined  # death_cause（god）
    assert "超时" not in joined  # player.fallback（god）
    assert "boom" not in joined  # rule.error（god）
    assert "我是预言家" in joined  # player.speech（public）
    assert "被放逐" in joined  # vote.resolved（public）


def test_public视角座位表无角色():
    doc = _export(view="public")
    assert all("role" not in s or s["role"] is None for s in doc["match"]["seats"])


def test_public视角不含发牌():
    doc = _export(view="public")
    texts = [e["text"] for seg in doc["segments"] for e in seg["entries"]]
    assert not any("发牌" in t for t in texts)


def test_导出空事件():
    doc = build_export(match_id=1, match_info=_match_info(), seats=_seats(),
                       events=[], usage=_usage(), view="god")
    assert doc["segments"] == []
    assert doc["usage"]["fallbacks"] == 0


# ---------- v2：展示文档（is_night / stage / votes / persona / index）----------
# 规格：docs/backend/11-export.md 第五节（is_night、段末 stage 快照、结构化 votes）


def _v2_events():
    """完整发牌（1-4 号）+ 夜刀 2 号 + 警长 3 号 + 放逐 3 号 + 开枪链 3→1。"""
    evs = [
        _ev(1, "match.created", {"seed": 42, "roles": {"wolf": 1}}, day=0, phase=""),
        _ev(2, "match.started", {"seed": 42}, day=0, phase=""),
        _ev(3, "role.dealt", {"seat": 1, "role": "villager"}, vis=seat(1), day=0, phase=""),
        _ev(4, "role.dealt", {"seat": 2, "role": "villager"}, vis=seat(2), day=0, phase=""),
        _ev(5, "role.dealt", {"seat": 3, "role": "hunter"}, vis=seat(3), day=0, phase=""),
        _ev(6, "role.dealt", {"seat": 4, "role": "wolf"}, vis=seat(4), day=0, phase=""),
        _ev(7, "phase.started", {"phase": "night_start", "day": 1, "label": "入夜"},
            phase="night_start"),
        _ev(8, "night.resolved", {"day": 1, "deaths": {"2": ""}}, phase="night_resolve"),
        _ev(9, "phase.started", {"phase": "sheriff_elect", "day": 1, "label": "警长竞选"},
            phase="sheriff_elect"),
        _ev(10, "sheriff.badge", {"action": "transfer", "to": 3}, phase="sheriff_elect"),
        _ev(11, "phase.started", {"phase": "speech_order", "day": 1, "label": "发言定序"},
            phase="speech_order"),
        _ev(12, "phase.started", {"phase": "day_vote", "day": 1, "label": "放逐投票"},
            phase="day_vote"),
        _ev(13, "vote.cast", {"seat": 1, "target": 3}, phase="day_vote"),
        _ev(14, "vote.cast", {"seat": 3, "target": 3}, phase="day_vote"),
        _ev(15, "vote.resolved", {"votes": {1: 3, 3: 3}, "scope": "exile", "exiled": 3,
                                  "tie": False, "tied": []}, phase="day_vote"),
        _ev(16, "phase.started", {"phase": "exile_resolve", "day": 1, "label": "放逐结算"},
            phase="exile_resolve"),
        _ev(17, "gun.shoot", {"seat": 3, "target": 1, "text": "带走"}, phase="exile_resolve"),
        _ev(18, "match.finished", {"winner": "good", "reason": "狼人全部出局"},
            phase="exile_resolve"),
    ]
    return evs


def _v2_export(view="god"):
    return build_export(match_id=1, match_info=_match_info(), seats=_seats(),
                        events=_v2_events(), usage=_usage(), view=view)


def test_v2_段含is_night():
    segs = _v2_export()["segments"]
    assert segs[0]["is_night"] is False  # 开局
    assert segs[1]["is_night"] is True  # 第一夜
    assert segs[2]["is_night"] is False  # 第一天
    assert segs[2]["day_index"] == 1


def test_v2_段末stage快照含开枪链与移徽():
    segs = _v2_export()["segments"]
    assert segs[0]["stage"] == {"alive": [1, 2, 3, 4], "sheriff": None}
    assert segs[1]["stage"] == {"alive": [1, 3, 4], "sheriff": 3}  # 夜刀 2 号 + 徽章移交 3 号
    assert segs[2]["stage"] == {"alive": [4], "sheriff": 3}  # 放逐 3 号 + 开枪带走 1 号


def test_v2_票回合结构化含警长两票():
    segs = _v2_export()["segments"]
    votes = segs[2]["votes"]
    assert votes == [{
        "title": "放逐投票", "scope": "exile",
        "votes": {1: 3, 3: 3}, "tally": {3: 3},  # 3 号是警长 → 2 票权重
        "exiled": 3, "tie": False,
    }]


def test_v2_public视角无role但stage与votes齐全():
    doc = _v2_export(view="public")
    assert all("role" not in s or s["role"] is None for s in doc["match"]["seats"])
    for seg in doc["segments"]:
        assert "stage" in seg
    assert doc["segments"][2]["votes"][0]["tally"] == {3: 3}


def test_v2_seats含persona名与回退():
    doc = _export(personas={"p1": {"name": "悍跳", "style": "强硬"}})
    rows = doc["match"]["seats"]
    assert rows[0]["persona_name"] == "悍跳"
    assert rows[0]["persona_style"] == "强硬"
    assert rows[1]["persona_name"] == "p2"  # 无配置回退 persona_id
    assert rows[1]["persona_style"] == ""  # 无配置回退空


def test_index_合并更新幂等(tmp_path):
    import json

    from app.export import index_entry, update_index

    p = tmp_path / "index.json"
    e1 = index_entry(match_id=1, seed=1, status="finished", winner="good",
                     reason="r", player_count=9, exported_at="t1", views=["god"])
    update_index(p, e1)
    e2 = index_entry(match_id=2, seed=2, status="finished", winner="wolf",
                     reason="r", player_count=9, exported_at="t2",
                     views=["god", "public"])
    update_index(p, e2)
    e1b = index_entry(match_id=1, seed=1, status="finished", winner="good",
                      reason="r", player_count=9, exported_at="t3",
                      views=["public"])
    update_index(p, e1b)
    doc = json.loads(p.read_text(encoding="utf-8"))
    assert [m["match_id"] for m in doc["matches"]] == [1, 2]  # 同局覆盖不重复
    m1 = doc["matches"][0]
    assert m1["views"] == ["god", "public"]  # views 取并集
    assert m1["exported_at"] == "t3"  # 最新导出覆盖