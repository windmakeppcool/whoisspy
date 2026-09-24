"""渲染逻辑测试（Red 先行）：事件流 → 分段对话 JSON。"""

import pytest

from app.core import Event, VisMeta
from app.export.dialog import render_dialog


def make_event(etype: str, payload: dict, day: int = 1, phase: str = "") -> Event:
    return Event(type=etype, payload=payload, day_index=day, phase=phase,
                 vis=VisMeta(level="public"))


class TestRenderDialog:
    def test_空事件流返回空段(self):
        result = render_dialog(match_id=1, game_type="werewolf", events=[])
        assert result["segments"] == []
        assert result["match_id"] == 1

    def test_按天夜分段标签(self):
        events = [
            make_event("player.speech", {"seat": 1, "text": "你好"}, day=1, phase="night"),
            make_event("player.speech", {"seat": 2, "text": "白天发言"}, day=1, phase="day_speech"),
            make_event("player.speech", {"seat": 3, "text": "第二天"}, day=2, phase="day_speech"),
        ]
        result = render_dialog(match_id=1, game_type="werewolf", events=events)
        labels = [s["label"] for s in result["segments"]]
        assert labels == ["第一夜", "第一天", "第二天"]

    def test_发言渲染为entries(self):
        events = [
            make_event("player.speech", {"seat": 3, "text": "我认为2号是狼"}, day=1, phase="day_speech"),
        ]
        result = render_dialog(match_id=1, game_type="werewolf", events=events)
        assert len(result["segments"]) == 1
        seg = result["segments"][0]
        assert seg["label"] == "第一天"
        assert seg["entries"] == [
            {"speaker": "3号", "type": "speech", "text": "我认为2号是狼"}
        ]

    def test_夜晚关键事件渲染为system(self):
        events = [
            make_event("night.kill_target", {"target": 5, "decided_by": "wolf1"}, day=1, phase="night"),
            make_event("night.resolved", {"dead": [5], "cause": "kill"}, day=1, phase="night"),
        ]
        result = render_dialog(match_id=1, game_type="werewolf", events=events)
        seg = result["segments"][0]
        assert seg["label"] == "第一夜"
        assert any(e["type"] == "system" for e in seg["entries"])
        kill_entry = next(e for e in seg["entries"] if "击杀" in e["text"] or "kill" in e["text"].lower())
        assert kill_entry["speaker"] is None

    def test_狼队频道消息(self):
        events = [
            make_event("channel.message", {"seat": 1, "text": "我刀5号"}, day=1, phase="night"),
        ]
        result = render_dialog(match_id=1, game_type="werewolf", events=events)
        seg = result["segments"][0]
        entry = seg["entries"][0]
        assert entry["type"] == "channel"
        assert entry["speaker"] == "1号"
        assert entry["text"] == "我刀5号"

    def test_夜晚结算读取deaths键_真实payload(self):
        """runner 实际产出 deaths={seat: cause}；键名不匹配会渲染成'平安夜'（bug 回归）。"""
        events = [
            make_event("night.resolved", {"day": 1, "deaths": {"1": "knife"}},
                       day=1, phase="night_resolve"),
        ]
        result = render_dialog(match_id=1, game_type="werewolf", events=events)
        texts = [e["text"] for e in result["segments"][0]["entries"]]
        assert any("死亡" in t and "1号" in t for t in texts)
        assert not any("平安夜" in t for t in texts)

    def test_女巫动作读取act键_真实payload(self):
        """runner 实际产出 act=save/poison；读错键会把用解药渲染成'不用药'（bug 回归）。"""
        events = [
            make_event("night.witch_action", {"seat": 8, "act": "save", "target": 0},
                       day=1, phase="witch_turn"),
        ]
        result = render_dialog(match_id=1, game_type="werewolf", events=events)
        texts = [e["text"] for e in result["segments"][0]["entries"]]
        assert any("解药" in t for t in texts)
        assert not any("不用药" in t for t in texts)

    def test_投票事件渲染(self):
        events = [
            make_event("vote.cast", {"seat": 2, "target": 5}, day=1, phase="day_vote"),
        ]
        result = render_dialog(match_id=1, game_type="werewolf", events=events)
        seg = result["segments"][0]
        entry = seg["entries"][0]
        assert entry["type"] == "vote"
        assert "2号" in entry["text"]
        assert "5号" in entry["text"]

    def test_内心独白渲染(self):
        events = [
            make_event("player.monologue", {"seat": 1, "text": "我是狼"}, day=1, phase="night"),
        ]
        result = render_dialog(match_id=1, game_type="werewolf", events=events)
        seg = result["segments"][0]
        entry = seg["entries"][0]
        assert entry["type"] == "monologue"
        assert entry["speaker"] == "1号"

    def test_遗言渲染(self):
        events = [
            make_event("player.last_words", {"seat": 4, "text": "我是好人"}, day=1, phase="day_exile"),
        ]
        result = render_dialog(match_id=1, game_type="werewolf", events=events)
        seg = result["segments"][0]
        entry = seg["entries"][0]
        assert entry["type"] == "last_words"
        assert entry["speaker"] == "4号"
        assert entry["text"] == "我是好人"

    def test_段内按序保留多个entries(self):
        events = [
            make_event("player.speech", {"seat": 1, "text": "第一个"}, day=1, phase="day_speech"),
            make_event("player.speech", {"seat": 2, "text": "第二个"}, day=1, phase="day_speech"),
            make_event("vote.cast", {"seat": 1, "target": 2}, day=1, phase="day_vote"),
        ]
        result = render_dialog(match_id=1, game_type="werewolf", events=events)
        # day_speech 和 day_vote 都是 day=1 → 同一段"第一天"
        assert len(result["segments"]) == 1
        seg = result["segments"][0]
        assert len(seg["entries"]) == 3
        assert seg["entries"][0]["text"] == "第一个"
        assert seg["entries"][1]["text"] == "第二个"
        assert seg["entries"][2]["type"] == "vote"

    def test_不同phase归为同一天(self):
        """night 和 day_speech 在 day=1 时应该是两段：第一夜、第一天"""
        events = [
            make_event("player.speech", {"seat": 1, "text": "夜话"}, day=1, phase="night"),
            make_event("player.speech", {"seat": 2, "text": "白天"}, day=1, phase="day_speech"),
        ]
        result = render_dialog(match_id=1, game_type="werewolf", events=events)
        labels = [s["label"] for s in result["segments"]]
        assert "第一夜" in labels
        assert "第一天" in labels
