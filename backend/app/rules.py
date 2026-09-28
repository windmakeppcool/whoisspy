"""狼人杀 standard-9 纯函数规则（docs/backend/05-rules.md）。

全部为无 IO 纯函数：发牌/定刀/计票/夜结算/胜负/动作校验/中性兜底。
规则书口径见 docs/games/werewolf.md。
"""

from __future__ import annotations

from random import Random
from typing import Any

from app.events import AskSpec, GameResult

RULESET = "standard-9"
ROLES = {"wolf": 3, "seer": 1, "witch": 1, "hunter": 1, "villager": 3}
WOLF_ROLES = {"wolf"}
GOD_ROLES = {"seer", "witch", "hunter"}
GUN_ROLES = {"hunter"}
DEATH_KNIFE, DEATH_POISON = "knife", "poison"
WOLF_MEETING_ROUNDS = 2  # CLI --wolf-rounds 可覆盖
MAX_DAYS = 8  # CLI --max-days 可覆盖


# ---------- 发牌 ----------

def deal(seed: int) -> dict[int, str]:
    """按种子发牌：9 角色洗牌后座位 1–9 依次领角色；同 seed 必得同分配。"""
    deck = [role for role, n in ROLES.items() for _ in range(n)]
    rng = Random(seed)
    rng.shuffle(deck)
    return {i + 1: deck[i] for i in range(len(deck))}


# ---------- 定刀 ----------

def decide_kill(proposals: dict[int, int], rng: Random,
                valid_targets) -> tuple[int | None, str]:
    """多数决定刀；平票 rng 决胜；无有效票 = 空刀。

    返回 (target, decided_by)：decided_by ∈ {"majority", "rng", "empty"}。
    非法目标（不在 valid_targets）的提案视作弃权。
    """
    valid = {s: t for s, t in proposals.items() if t in valid_targets}
    if not valid:
        return None, "empty"
    counts: dict[int, int] = {}
    for t in valid.values():
        counts[t] = counts.get(t, 0) + 1
    top = max(counts.values())
    leaders = sorted(t for t, c in counts.items() if c == top)
    if len(leaders) == 1:
        return leaders[0], "majority"
    return rng.choice(leaders), "rng"


# ---------- 计票 ----------

def tally_votes(votes: dict[int, int], sheriff: int | None = None) -> dict[str, Any]:
    """计票：警长的非零票计 2 票权重；0 = 弃权。

    返回 {exiled, tie, tied}：唯一最高 → exiled=最高者；并列 → tie=True + tied。
    """
    counts: dict[int, int] = {}
    for voter, target in votes.items():
        if not target:
            continue
        counts[target] = counts.get(target, 0) + (2 if voter == sheriff else 1)
    if not counts:
        return {"exiled": None, "tie": False, "tied": []}
    top = max(counts.values())
    leaders = sorted(t for t, c in counts.items() if c == top)
    if len(leaders) == 1:
        return {"exiled": leaders[0], "tie": False, "tied": []}
    return {"exiled": None, "tie": True, "tied": leaders}


# ---------- 夜结算矩阵 ----------

def resolve_night(night: dict[str, Any]) -> dict[int, str]:
    """夜结算（规则书二）：{kill, saved, poison} → {seat: cause}。

    毒优先级：狼杀 > 女巫毒——同刀同毒且未救认定刀杀（可开枪）；
    已救则刀被化解仍死于毒（不能开枪）；空刀（kill 为 0/None）无刀杀。
    """
    kill = night.get("kill") or None  # 0/None 一律视作空刀
    saved = bool(night.get("saved"))
    poison = night.get("poison") or None
    deaths: dict[int, str] = {}
    if poison is not None:
        deaths[poison] = DEATH_POISON  # 解药不挡毒
    if kill is not None and kill == poison:
        deaths[kill] = DEATH_KNIFE if not saved else DEATH_POISON
    elif kill is not None and not saved:
        deaths[kill] = DEATH_KNIFE
    return deaths


# ---------- 胜负 ----------

def check_winner(state, *, day_cycle_done: bool,
                 max_days: int = MAX_DAYS) -> GameResult | None:
    """胜负判定（规则书五）。检查时机只有两处：夜结算后、放逐结算后（day_cycle_done）。"""
    roles, alive = state.roles, state.alive
    alive_wolves = [s for s in roles if alive.get(s) and roles[s] in WOLF_ROLES]
    if not alive_wolves:
        return GameResult(winner="good", reason="狼人全部出局")
    alive_gods = [s for s in roles if alive.get(s) and roles[s] in GOD_ROLES]
    alive_villagers = [s for s in roles if alive.get(s) and roles[s] == "villager"]
    alive_good = [s for s in roles if alive.get(s) and roles[s] not in WOLF_ROLES]
    if not alive_gods:
        return GameResult(winner="wolf", reason="神职全部出局（屠边）")
    if not alive_villagers:
        return GameResult(winner="wolf", reason="平民全部出局（屠边）")
    if len(alive_wolves) >= len(alive_good):
        return GameResult(winner="wolf",
                          reason=f"存活狼数 {len(alive_wolves)} ≥ 好人数 {len(alive_good)}（屠城）")
    if state.day >= max_days and day_cycle_done:
        return GameResult(winner="wolf", reason=f"第 {max_days} 天白天结束仍有狼存活")
    return None


# ---------- 动作校验 ----------

# 各阶段允许的动作类型（与 AskSpec.action_type 对应的合法集合）
_PHASE_ACTIONS: dict[str, tuple[str, ...]] = {
    "wolf_meeting": ("kill",),
    "closing": ("kill",),
    "seer_check": ("check",),
    "witch_turn": ("save", "poison", "pass"),
    "speech_order": ("speech_order",),
    "ballot": ("vote",),
    "day_vote": ("vote",),
    "sheriff_register": ("register",),
    "last_words": ("speech",),
    "serial_speech": ("speech",),
    "day_speech": ("speech",),
    "gun": ("shoot",),
    "badge": ("badge",),
}


def validate_action(state, phase: str, ask_spec: AskSpec,
                    action: dict[str, Any]) -> dict[str, Any]:
    """校验并归一动作；非法输入降级为中性动作（LLM 输出不可信是常态）。

    规则（05-rules 七）：
    - type 必须是该阶段允许的类型之一；
    - target 必须 ∈（候选集 ∩ 存活），否则按弃权（target=0）；
    - 女巫特例：解药已用/空刀夜 → save 降级 pass；毒药已用 → poison 降级 pass；
    - register 只取 yes 布尔；speech 类 target 恒 0。
    """
    neutral = neutral_action(phase)
    allowed = _PHASE_ACTIONS.get(phase, ())
    atype = str(action.get("type", "") or "")
    if atype not in allowed:
        return neutral

    alive = {s for s in state.roles if state.alive.get(s)}
    if atype == "register":
        return {"type": "register", "yes": bool(action.get("yes", False))}
    if atype == "speech":
        return {"type": "speech", "target": 0}

    candidates = {_to_int(c) for c in (ask_spec.candidates or [])}
    valid_targets = (candidates & alive) if candidates else alive
    target = _to_int(action.get("target"))
    if atype == "save":
        knife = state.night.get("kill")
        if state.used_save or not knife:
            return neutral
        return {"type": "save", "target": 0}
    if atype == "poison":
        if state.used_poison or target not in valid_targets:
            return neutral
        return {"type": "poison", "target": target}
    if target not in valid_targets:
        target = 0  # 其余类型：非法目标按弃权处理（不是整条动作作废）
    return {"type": atype, "target": target}


# ---------- 中性兜底 ----------

# 每阶段的中性动作：兜底绝不替玩家做决定（女巫超时绝不用解药，猎人超时绝不开枪）
_NEUTRAL_ACTIONS: dict[str, dict[str, Any]] = {
    "wolf_meeting": {"type": "kill", "target": 0},
    "closing": {"type": "kill", "target": 0},
    "seer_check": {"type": "check", "target": 0},
    "witch_turn": {"type": "pass", "target": 0},
    "speech_order": {"type": "speech_order", "target": 0},
    "ballot": {"type": "vote", "target": 0},
    "day_vote": {"type": "vote", "target": 0},
    "sheriff_register": {"type": "register", "yes": False},
    "last_words": {"type": "speech", "target": 0},
    "serial_speech": {"type": "speech", "target": 0},
    "day_speech": {"type": "speech", "target": 0},
    "gun": {"type": "shoot", "target": 0},
    "badge": {"type": "badge", "target": 0},
}


def neutral_action(phase: str) -> dict[str, Any]:
    """该阶段的中性兜底动作；未知阶段默认 pass。"""
    return dict(_NEUTRAL_ACTIONS.get(phase, {"type": "pass", "target": 0}))


def _to_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0