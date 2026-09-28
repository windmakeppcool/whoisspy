"""prompts 模块测试（Red 先行）：docs/backend/06-prompts.md 第二/三节。"""

from app.events import AskSpec
from app.prompts import SLICES, slices_for
from app.prompts import (
    badge_spec,
    ballot_spec,
    closing_spec,
    gun_spec,
    register_spec,
    seer_check_spec,
    speech_order_spec,
    speech_spec,
    witch_turn_spec,
    wolf_meeting_spec,
)


def test_切片九键齐全():
    assert set(SLICES) == {"overview", "night_wolf", "night_seer", "night_witch",
                           "gun_skill", "sheriff_elect", "sheriff_power",
                           "day_speech", "day_vote"}


def test_overview切片含胜负与字数上限():
    assert "240" in SLICES["overview"]
    assert "狼人" in SLICES["overview"]


def test_slices_for注入映射():
    assert slices_for("wolf_meeting") == ["overview", "night_wolf"]
    assert slices_for("closing") == ["overview", "night_wolf"]
    assert slices_for("seer_check") == ["overview", "night_seer"]
    assert slices_for("witch_turn") == ["overview", "night_witch"]
    assert slices_for("gun") == ["overview", "gun_skill"]
    assert slices_for("sheriff_register") == ["overview", "sheriff_elect"]
    assert slices_for("speech_order") == ["overview", "day_speech", "sheriff_power"]
    assert slices_for("day_vote") == ["overview", "day_vote", "sheriff_power"]
    assert slices_for("badge") == ["overview", "sheriff_power"]
    assert slices_for("day_speech") == ["overview", "day_speech", "sheriff_power"]
    assert slices_for("last_words") == ["overview", "day_speech"]


def test_狼队模板():
    s = wolf_meeting_spec([1, 2, 3, 4])
    assert s.action_type == "kill"
    assert s.candidates == [1, 2, 3, 4]
    assert "商量今晚刀谁" in s.prompt


def test_收刀模板():
    s = closing_spec([1, 2, 3])
    assert s.action_type == "kill"
    assert "0 为弃权/空刀" in s.prompt


def test_预言家模板():
    s = seer_check_spec([1, 2, 3])
    assert s.action_type == "check"
    assert "0 为不查验" in s.prompt


def test_女巫模板带刀口信息():
    s = witch_turn_spec([1, 2, 3], knife_text="当晚刀口：5 号玩家（用解药可救活）。")
    assert s.action_type == "save"
    assert s.candidates == [1, 2, 3]
    assert "当晚刀口：5 号玩家" in s.prompt_extra
    assert "pass/save 时 target=0" in s.prompt


def test_警长定序模板():
    s = speech_order_spec([1, 2, 3])
    assert s.action_type == "speech_order"
    assert "指定今天从哪位玩家开始发言" in s.prompt


def test_投票模板带标题():
    s = ballot_spec("放逐投票", [1, 2, 3])
    assert s.action_type == "vote"
    assert "投票（放逐投票）" in s.prompt
    assert s.candidates == [1, 2, 3]


def test_发言模板按purpose区分():
    assert "竞选宣言" in speech_spec("sheriff_speech").prompt
    assert "PK" in speech_spec("pk_speech").prompt
    assert "白天发言" in speech_spec("speech").prompt
    assert "遗言" in speech_spec("last_words").prompt
    for s in [speech_spec("speech"), speech_spec("sheriff_speech"),
              speech_spec("pk_speech"), speech_spec("last_words")]:
        assert s.action_type == "speech"
        assert s.candidates == []


def test_上警模板():
    s = register_spec()
    assert s.action_type == "register"
    assert "yes" in s.prompt


def test_开枪与移徽模板():
    s = gun_spec([1, 2, 3])
    assert s.action_type == "shoot"
    assert "放弃开枪" in s.prompt
    s = badge_spec([1, 2, 3])
    assert s.action_type == "badge"
    assert "撕毁警徽" in s.prompt