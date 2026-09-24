"""狼人杀规则纯函数（唯一板子：standard-9）。

standard-9 = 9 人：狼人 ×3 + 预言家 + 女巫 + 猎人 + 平民 ×3（无守卫、无狼王）。
单板收敛的理由见 docs/decisions.md（D23）：配置面越小，出错面越小。

全部为无副作用纯函数，随机只经传入的 rng（结果由调用方写入事件）。
规则依据 docs/games/werewolf.md。
"""

from __future__ import annotations

from random import Random
from typing import Any

from app.core import BoardSpec, GameResult, RoleAssignment

# ---------- 角色 ----------

ROLE_WEREWOLF = "wolf"
ROLE_SEER = "seer"
ROLE_WITCH = "witch"
ROLE_HUNTER = "hunter"
ROLE_VILLAGER = "villager"

WOLF_ROLES = frozenset({ROLE_WEREWOLF})  # 狼阵营
GUN_ROLES = frozenset({ROLE_HUNTER})  # 死亡可开枪的角色（被毒死除外）
GOD_ROLES = frozenset({ROLE_SEER, ROLE_WITCH, ROLE_HUNTER})  # 神职（屠边对象）

# ---------- 死因 ----------

DEATH_BY_KNIFE = "knife"  # 刀死（可开枪）
DEATH_BY_POISON = "poison"  # 毒死（不能开枪）

# ---------- 板子 ----------

RULESET = "standard-9"
PLAYER_COUNT = 9
STANDARD9_ROLES: dict[str, int] = {
    ROLE_WEREWOLF: 3,
    ROLE_SEER: 1,
    ROLE_WITCH: 1,
    ROLE_HUNTER: 1,
    ROLE_VILLAGER: 3,
}


def _fmt_roles(roles: dict[str, int]) -> str:
    return "+".join(f"{n}{role}" for role, n in roles.items())


def validate_board(cfg: dict[str, Any]) -> BoardSpec:
    """校验板子配置：只接受 standard-9 的固定 9 人组合。"""
    ruleset = cfg.get("ruleset", RULESET)
    if ruleset != RULESET:
        raise ValueError(f"只支持 ruleset={RULESET}，收到 {ruleset!r}")
    roles = dict(cfg.get("roles") or {})
    if any(n < 0 for n in roles.values()):
        raise ValueError("角色数量不能为负")
    if roles != STANDARD9_ROLES:
        raise ValueError(
            f"{RULESET} 仅支持固定组合 {_fmt_roles(STANDARD9_ROLES)}，收到 {_fmt_roles(roles)}")
    rounds = int(cfg.get("wolf_meeting_rounds", 2))
    if rounds < 0:
        raise ValueError("wolf_meeting_rounds 不能为负")
    days = int(cfg.get("max_days", 8))
    if days < 1:
        raise ValueError("max_days 至少为 1")
    return BoardSpec(game_type="werewolf", ruleset=RULESET, roles=dict(STANDARD9_ROLES),
                     wolf_meeting_rounds=rounds, max_days=days)


# ---------- 发牌 ----------

def deal_roles(spec: BoardSpec, rng: Random) -> list[RoleAssignment]:
    """把角色列表洗牌后按座位 1..n 分配（同种子可复现）。"""
    bag = spec.role_list
    if len(bag) != PLAYER_COUNT:
        raise ValueError(f"角色总数 {len(bag)} 与标准 9 人局不符")
    rng.shuffle(bag)
    return [RoleAssignment(seat=i + 1, role=role) for i, role in enumerate(bag)]


# ---------- 计票 ----------

def tally_votes(votes: dict[int, int], sheriff: int | None = None) -> dict[str, Any]:
    """计票。votes: voter_seat -> target_seat(0=弃权)。警长票权重 2。

    返回 {"exiled": seat|None, "tie": bool, "tied": list[seat]}。0 或缺失不计票。
    """
    weights: dict[int, int] = {}
    for voter, target in votes.items():
        if not target:
            continue
        w = 2 if (sheriff is not None and voter == sheriff) else 1
        weights[target] = weights.get(target, 0) + w
    if not weights:
        return {"exiled": None, "tie": True, "tied": []}
    top = max(weights.values())
    leaders = sorted(t for t, c in weights.items() if c == top)
    if len(leaders) > 1:
        return {"exiled": None, "tie": True, "tied": leaders}
    return {"exiled": leaders[0], "tie": False, "tied": leaders}


# ---------- 定刀多数决 ----------

def decide_kill(proposals: dict[int, int], rng: Random,
                valid_targets: set[int] | None = None) -> tuple[int | None, str]:
    """狼队收刀：并行提案多数决。

    proposals: wolf_seat -> target_seat(0=弃权)。
    返回 (target, decided_by)：decided_by ∈ majority / tie_rng / empty。
    平票用 rng 决出（结果由调用方写入事件）；无合规提案 = 空刀。
    """
    counts: dict[int, int] = {}
    for _wolf, target in proposals.items():
        if not target:
            continue
        if valid_targets is not None and target not in valid_targets:
            continue
        counts[target] = counts.get(target, 0) + 1
    if not counts:
        return None, "empty"
    top = max(counts.values())
    leaders = sorted(t for t, c in counts.items() if c == top)
    if len(leaders) > 1:
        return rng.choice(leaders), "tie_rng"
    return leaders[0], "majority"


# ---------- 夜间结算 ----------

def resolve_night(night: dict[str, Any]) -> dict[str, Any]:
    """夜间结算。输入 kill/saved/poison，输出 {"deaths": {seat: death_cause}}。

    矩阵（docs/games/werewolf.md，standard-9 无守卫）：
    - 空刀（kill 为 None/0）无人死于刀 → 平安夜（解药不可用于空刀口）；
    - 解药只挡刀：K 被救 → 免死；
    - 毒不被解药挡；
    - 同刀同毒：未被救 → 按「狼杀 > 女巫毒」认定刀杀（可开枪）；
      已被救 → 刀被解药化解，仍死于毒（不可开枪）。
    """
    kill = night.get("kill") or None  # 0 与 None 都表示空刀
    saved = bool(night.get("saved"))
    poison = night.get("poison") or None

    deaths: dict[int, str] = {}
    if kill is not None and not saved:
        deaths[kill] = DEATH_BY_KNIFE
    if poison is not None and poison not in deaths:
        deaths[poison] = DEATH_BY_POISON
    return {"deaths": deaths}


# ---------- 胜负 ----------

def _alive_count(roles: dict[int, str], alive: dict[int, bool], predicate) -> int:
    return sum(1 for s, r in roles.items() if alive.get(s) and predicate(r))


def check_winner(roles: dict[int, str], alive: dict[int, bool], *,
                 day: int = 1, max_days: int = 8,
                 day_cycle_done: bool = False) -> GameResult | None:
    """standard-9 胜负：狼胜四条路径（神职屠边 / 平民屠边 / 屠城 / 时限），好人胜=狼全灭。

    day_cycle_done：当前是否已走完第 day 天的白天流程（放逐结算之后）。
    时限只在该天白天真正结束、且仍无狼胜/好人胜时生效——
    避免「第 8 天白天还没打就判狼胜」的差一天。
    """
    wolves = _alive_count(roles, alive, lambda r: r in WOLF_ROLES)
    goods = _alive_count(roles, alive, lambda r: r not in WOLF_ROLES)
    if wolves == 0:
        return GameResult(winner="good", reason="狼人阵营全部出局")
    gods = _alive_count(roles, alive, lambda r: r in GOD_ROLES)
    villagers = _alive_count(roles, alive, lambda r: r == ROLE_VILLAGER)
    if gods == 0:
        return GameResult(winner="wolf", reason="神职全部出局（屠边）")
    if villagers == 0:
        return GameResult(winner="wolf", reason="平民全部出局（屠边）")
    if wolves >= goods:
        return GameResult(winner="wolf", reason=f"存活狼 {wolves} ≥ 存活好人 {goods}（屠城）")
    if day_cycle_done and day >= max_days:
        return GameResult(winner="wolf", reason=f"第 {max_days} 天白天结束仍有狼存活")
    return None
