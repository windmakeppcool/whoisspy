"""狼人杀 prompt 规则切片与指令模板（docs/backend/06-prompts.md）。

游戏知识归属地之一：切片文本（第 1/6 层）与各调用点的指令模板（第 6 层）。
"""

from __future__ import annotations

from app.events import AskSpec

SLICES: dict[str, str] = {
    "overview": (
        "【游戏规则·总览】这是标准 9 人局狼人杀：狼人 ×3、预言家、女巫、猎人、平民 ×3。"
        "狼人夜晚刀人、白天隐藏；好人通过发言与投票找出狼人。"
        "好人胜 = 狼人全部出局；狼胜 = 神职全灭、或平民全灭、或存活狼数 ≥ 存活好人数、"
        "或第 8 天白天结束仍有狼存活。发言上限 240 字。请始终以 JSON 格式回应。"
    ),
    "night_wolf": (
        "【狼队规则】你与狼队友在夜间私密频道交流（其他玩家看不到）。"
        "商讨后各自提交刀人目标，得票最高的目标生效；平票随机；全部弃权则空刀。"
        "建议与队友配合伪装，白天不要暴露同队关系。"
    ),
    "night_seer": (
        "【预言家规则】每晚可查验一名玩家的阵营（好人/狼人）。"
        "查验结果仅你可见，何时公开由你决定（起跳时机是重要策略）。"
    ),
    "night_witch": (
        "【女巫规则】你有一瓶解药和一瓶毒药，每晚最多用一瓶。"
        "解药只能救当晚被狼刀的人（空刀之夜无法用药）；毒药毒死一人，毒死不能被救、不能开枪。"
        "请求中会给出「当晚刀口」时，说明解药尚在。"
    ),
    "day_speech": (
        "【发言规则】按座位顺序发言，每人上限 240 字。"
        "基于场上信息（发言、投票、死讯）推理阵营，注意他人发言中的矛盾。"
    ),
    "day_vote": (
        "【投票规则】投出你认为最像狼的人（0 表示弃权）。"
        "得票最高者出局；平票则平票者再发言后全体重投，仍平票则平安日无人出局。"
        "被投出者可留遗言。"
    ),
    "sheriff_elect": (
        "【警长竞选】存活玩家可选择上警。恰 1 人上警自动当选；无人/全员上警则警徽丢失。"
        "上警者发表竞选宣言后，由未上警玩家投票，得票最高者当选；平票进入 PK "
        "（平票者再发言、其余玩家再投），仍平票则警徽丢失。"
    ),
    "sheriff_power": (
        "【警长权力】投票时拥有 2 票权重，可在投票前归票表明意向；"
        "死亡时必须移交警徽给存活玩家或撕毁警徽。"
    ),
    "gun_skill": (
        "【开枪规则】猎人在非毒死（被刀/被放逐）时可开枪带走一名存活玩家；"
        "被枪杀者不再连锁开枪。被女巫毒死不能开枪。"
    ),
}

# 阶段 → 注入切片（overview 恒在第 1 层，其余全在第 6 层）
_STEP_SLICES: dict[str, list[str]] = {
    "wolf_meeting": ["night_wolf"],
    "closing": ["night_wolf"],
    "seer_check": ["night_seer"],
    "witch_turn": ["night_witch"],
    "gun": ["gun_skill"],
    "sheriff_elect": ["sheriff_elect"],
    "sheriff_register": ["sheriff_elect"],
    "speech_order": ["day_speech", "sheriff_power"],
    "day_speech": ["day_speech", "sheriff_power"],
    "serial_speech": ["day_speech"],
    "last_words": ["day_speech"],
    "ballot": ["day_vote"],
    "day_vote": ["day_vote", "sheriff_power"],
    "badge": ["sheriff_power"],
    "exile_resolve": ["day_vote"],
}


def slices_for(phase: str) -> list[str]:
    """该阶段注入的切片键（首项恒为 overview）。"""
    return ["overview"] + _STEP_SLICES.get(phase, [])


# ---------- 指令模板（第 6 层动作指令） ----------

def wolf_meeting_spec(candidates: list[int]) -> AskSpec:
    return AskSpec(action_type="kill", candidates=list(candidates),
                   prompt="狼队夜聊：与队友商量今晚刀谁，然后提交你的刀人目标。")


def closing_spec(candidates: list[int]) -> AskSpec:
    return AskSpec(action_type="kill", candidates=list(candidates),
                   prompt="收刀：请提交最终刀人目标（0 为弃权/空刀）。")


def seer_check_spec(candidates: list[int]) -> AskSpec:
    return AskSpec(action_type="check", candidates=list(candidates),
                   prompt="预言家：选择今晚查验的玩家。0 为不查验。")


def witch_turn_spec(candidates: list[int], *,
                    knife_text: str = "",
                    action_type: str = "save") -> AskSpec:
    return AskSpec(
        action_type=action_type,
        candidates=list(candidates),
        prompt=("女巫：提交 action，type 为 save(救刀口)/poison(毒人)/pass(不用药)。"
                "target 为目标座位，pass/save 时 target=0。"),
        prompt_extra=knife_text)


def speech_order_spec(candidates: list[int]) -> AskSpec:
    return AskSpec(action_type="speech_order", candidates=list(candidates),
                   prompt="你是警长：指定今天从哪位玩家开始发言"
                          "（其余存活玩家按座位号顺序依次发言）。")


def ballot_spec(title: str, candidates: list[int]) -> AskSpec:
    return AskSpec(action_type="vote", candidates=list(candidates),
                   prompt=f"投票（{title}）：投出你最怀疑的玩家（0 为弃权）。")


def speech_spec(purpose: str = "speech") -> AskSpec:
    """发言类调用：purpose ∈ speech/sheriff_speech/pk_speech/last_words。"""
    prompts = {
        "sheriff_speech": "发表警长竞选宣言：说服大家把票投给你。",
        "pk_speech": "放逐投票平票，你进入 PK：发表最后陈述争取留下。",
        "last_words": "你已出局，请发表遗言。",
    }
    return AskSpec(action_type="speech",
                   prompt=prompts.get(purpose, "白天发言：陈述你的判断与推理。"))


def register_spec() -> AskSpec:
    return AskSpec(action_type="register",
                   prompt="警长竞选：是否上警（action 的 yes 字段 true/false）。")


def gun_spec(candidates: list[int]) -> AskSpec:
    return AskSpec(action_type="shoot", candidates=list(candidates),
                   prompt="你倒下了——开枪带走一名玩家（0 为放弃开枪）。")


def badge_spec(candidates: list[int]) -> AskSpec:
    return AskSpec(action_type="badge", candidates=list(candidates),
                   prompt="临终移交警徽：target 为继承座位（0 = 撕毁警徽）。")