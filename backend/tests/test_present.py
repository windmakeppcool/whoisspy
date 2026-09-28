"""present 观赛文案测试（Red 先行）：docs/backend/11-export.md 第一节。"""

from app.events import Event, god, public, seat
from app.present import Line, present


def _ev(type_, payload, vis=None, day=1, phase="x"):
    return Event(seq=1, type=type_, day_index=day, phase=phase,
                 payload=payload, vis=vis or public())


def test_阶段边界():
    got = present(_ev("phase.started", {"phase": "night_start", "day": 2, "label": "入夜"}))
    assert got == Line(kind="phase", seat=None, text="—— 入夜（第 2 天）——")


def test_发言与遗言():
    got = present(_ev("player.speech", {"seat": 2, "text": "我发言"}))
    assert got == Line(kind="speech", seat=2, text="2 号：我发言")
    got = present(_ev("player.last_words", {"seat": 3, "text": "遗言"}))
    assert got == Line(kind="last_words", seat=3, text="3 号（遗言）：遗言")


def test_频道与独白():
    got = present(_ev("channel.message", {"seat": 1, "text": "刀 5"}, vis=seat(1)))
    assert got == Line(kind="channel", seat=1, text="1 号（狼队频道）：刀 5")
    got = present(_ev("player.monologue", {"seat": 1, "text": "盘一下"}, vis=god()))
    assert got == Line(kind="monologue", seat=1, text="1 号（内心）：盘一下")


def test_定刀():
    got = present(_ev("night.kill_target", {"target": 5, "decided_by": "majority", "proposals": {}}, vis=god()))
    assert got.text == "狼队选择击杀 5 号"
    got = present(_ev("night.kill_target", {"target": None, "decided_by": "empty", "proposals": {}}, vis=god()))
    assert got.text == "狼队空刀"


def test_查验():
    got = present(_ev("night.seer_query", {"seat": 2, "target": 1}, vis=god()))
    assert got.text == "预言家查验 1 号"
    got = present(_ev("night.seer_query", {"seat": 2, "target": 0}, vis=god()))
    assert got.text == "预言家今晚未查验"
    got = present(_ev("night.seer_result", {"seat": 2, "target": 1, "verdict": "wolf"}, vis=seat(2)))
    assert got.text == "查验 1 号：狼人"


def test_女巫用药():
    assert present(_ev("night.witch_action", {"seat": 3, "act": "save", "target": 0}, vis=god())).text == "女巫使用解药"
    assert present(_ev("night.witch_action", {"seat": 3, "act": "poison", "target": 4}, vis=god())).text == "女巫毒杀 4 号"
    assert present(_ev("night.witch_action", {"seat": 3, "act": "pass", "target": 0}, vis=god())).text == "女巫不用药"


def test_死讯与死因():
    got = present(_ev("night.resolved", {"day": 1, "deaths": {"3": "", "5": ""}}, day=1))
    assert got.text == "第 1 夜：3 号、5 号 死亡"
    got = present(_ev("night.resolved", {"day": 1, "deaths": {}}, day=1))
    assert got.text == "第 1 夜：平安夜"
    got = present(_ev("night.death_cause", {"causes": {3: "knife", 5: "poison"}}, vis=god()))
    assert got.text == "死因：3 号=刀杀、5 号=毒杀"


def test_技能状态():
    got = present(_ev("skill_state.notice", {"seat": 6, "can_shoot": True}, vis=seat(6)))
    assert got.text == "6 号猎人：可以开枪"
    got = present(_ev("skill_state.notice", {"seat": 6, "can_shoot": False}, vis=seat(6)))
    assert got.text == "6 号猎人：今晚不能开枪"


def test_警长():
    assert present(_ev("sheriff.registered", {"seats": [1, 4]})).text == "上警：1 号、4 号"
    assert present(_ev("sheriff.registered", {"seats": []})).text == "无人上警"
    assert present(_ev("sheriff.badge", {"action": "transfer", "to": 4})).text == "4 号当选警长"
    assert present(_ev("sheriff.badge", {"action": "destroy"})).text == "警徽被撕毁"


def test_发言顺序():
    got = present(_ev("day.speech_order", {"order": [2, 3, 5], "start": 2, "decided_by": "sheriff"}))
    assert got.text == "发言顺序：2→3→5 号"


def test_投票():
    assert present(_ev("vote.cast", {"seat": 3, "target": 5})).text == "3 号投票给 5 号"
    assert present(_ev("vote.cast", {"seat": 3, "target": 0})).text == "3 号弃票"
    got = present(_ev("vote.resolved", {"scope": "exile", "exiled": 5, "tie": False, "tied": []}))
    assert got.text == "5 号被放逐出局"
    got = present(_ev("vote.resolved", {"scope": "exile", "exiled": None, "tie": True, "tied": [2, 3]}))
    assert got.text == "平票，无人出局"
    got = present(_ev("vote.resolved", {"scope": "sheriff", "exiled": 4, "tie": False, "tied": []}))
    assert got.text == "4 号当选警长"
    got = present(_ev("vote.resolved", {"scope": "sheriff", "exiled": None, "tie": True, "tied": [2, 3]}))
    assert got.text == "警长投票平票"


def test_开枪():
    assert present(_ev("gun.shoot", {"seat": 6, "target": 2, "text": ""})).text == "6 号开枪带走 2 号"
    assert present(_ev("gun.shoot", {"seat": 6, "target": 0, "text": ""})).text == "6 号放弃开枪"


def test_诊断事件():
    got = present(_ev("player.fallback", {"seat": 1, "reason": "超时", "purpose": "vote"}, vis=god()))
    assert got.text == "⚠ 1 号调用失败走兜底（超时）"
    got = present(_ev("rule.error", {"phase": "day_vote", "reason": "boom"}, vis=god()))
    assert got.text == "⚠ 规则异常（day_vote）：boom"


def test_对局结束():
    got = present(_ev("match.finished", {"winner": "wolf", "reason": "屠城"}))
    assert got.text == "🏁 对局结束：狼人阵营获胜（屠城）"
    got = present(_ev("match.stopped", {"reason": "手动终止"}))
    assert got.text == "⏹ 对局终止：手动终止"


def test_发牌god视角():
    got = present(_ev("role.dealt", {"seat": 1, "role": "wolf"}, vis=seat(1)))
    assert got.text == "发牌：1 号 = wolf"


def test_不上屏事件():
    for t, p in [("match.created", {"seed": 1}),
                 ("match.started", {"seed": 1}),
                 ("night.started", {"day": 1}),
                 ("channel.round.started", {"channel": "wolf", "members": [1, 2]}),
                 ("channel.round.ended", {"channel": "wolf", "proposals": {}})]:
        assert present(_ev(t, p, vis=god())) is None, t