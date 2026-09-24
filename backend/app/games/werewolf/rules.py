"""狼人杀规则纯函数：发牌校验/发牌/计票/定刀/夜间结算/胜负。

全部为无副作用纯函数，随机只经传入的 rng（结果由调用方写入事件）。
规则依据 docs/games/werewolf.md（两套 ruleset）。
"""

from __future__ import annotations

import math
from random import Random
from typing import Any

from app.core import BoardSpec, GameResult, RoleAssignment

ROLE_WEREWOLF = "wolf"
ROLE_WOLF_KING = "wolf_king"
ROLE_SEER = "seer"
ROLE_WITCH = "witch"
ROLE_HUNTER = "hunter"
ROLE_GUARD = "guard"
ROLE_VILLAGER = "villager"

ROLE_DEATH_BY_POISON = "poison"  # 毒死（猎人/狼王不能开枪）
ROLE_DEATH_BY_KNIFE = "knife"  # 刀死（可开枪）

WOLF_ROLES = {ROLE_WEREWOLF, ROLE_WOLF_KING}
GUN_ROLES = {ROLE_HUNTER, ROLE_WOLF_KING}  # 死亡可开枪的角色
GOD_ROLES = {ROLE_SEER, ROLE_WITCH, ROLE_HUNTER, ROLE_GUARD}  # standard 神职

MIN_PLAYERS, MAX_PLAYERS = 6, 10


# ---------- 发牌校验 ----------

def _check_role_sum(roles: dict[str, int]) -> None:
    if any(n < 0 for n in roles.values()):
        raise ValueError("角色数量不能为负")


def validate_board_minimal(cfg: dict[str, Any]) -> BoardSpec:
    """minimal：6≤n≤10，狼 1~ceil(n/3)，预 0~2，民≥1，仅允许狼/预/民三种角色。"""
    roles = dict(cfg.get("roles") or {})
    _check_role_sum(roles)
    unknown = set(roles) - {ROLE_WEREWOLF, ROLE_SEER, ROLE_VILLAGER}
    if unknown:
        raise ValueError(f"minimal 规则集不支持角色: {sorted(unknown)}")
    n = sum(roles.values())
    if not (MIN_PLAYERS <= n <= MAX_PLAYERS):
        raise ValueError(f"minimal 人数须在 {MIN_PLAYERS}~{MAX_PLAYERS}，当前 {n}")
    wolves = roles.get(ROLE_WEREWOLF, 0)
    max_wolves = math.ceil(n / 3)
    if not (1 <= wolves <= max_wolves):
        raise ValueError(f"狼数须在 1~{max_wolves}，当前 {wolves}")
    seers = roles.get(ROLE_SEER, 0)
    if not (0 <= seers <= 2):
        raise ValueError(f"预言家须在 0~2，当前 {seers}")
    if roles.get(ROLE_VILLAGER, 0) < 1:
        raise ValueError("平民至少 1 名")
    rounds = cfg.get("wolf_meeting_rounds", 2)
    days = cfg.get("max_days", 8)
    return BoardSpec(game_type="werewolf", ruleset="minimal", roles=roles,
                     wolf_meeting_rounds=int(rounds), max_days=int(days))


STANDARD12_ROLES = {
    ROLE_WEREWOLF: 3, ROLE_WOLF_KING: 1, ROLE_SEER: 1, ROLE_WITCH: 1,
    ROLE_HUNTER: 1, ROLE_GUARD: 1, ROLE_VILLAGER: 4,
}

STANDARD9_ROLES = {
    ROLE_WEREWOLF: 3, ROLE_SEER: 1, ROLE_WITCH: 1, ROLE_HUNTER: 1,
    ROLE_VILLAGER: 3,
}


def validate_board_standard(cfg: dict[str, Any]) -> BoardSpec:
    """standard-12：固定 12 人组合（暂不开放 custom 改神职数）。"""
    return _validate_fixed(cfg, STANDARD12_ROLES, "standard-12")


def validate_board_standard9(cfg: dict[str, Any]) -> BoardSpec:
    """standard-9：固定 9 人组合 3狼+预女猎+3民（无守卫，暂不开放 custom）。"""
    return _validate_fixed(cfg, STANDARD9_ROLES, "standard-9")


def _validate_fixed(cfg: dict[str, Any], expected: dict[str, int], ruleset: str) -> BoardSpec:
    roles = dict(cfg.get("roles") or {})
    _check_role_sum(roles)
    if roles != expected:
        raise ValueError(f"{ruleset} 仅支持固定组合: {_fmt_roles(expected)}")
    rounds = cfg.get("wolf_meeting_rounds", 2)
    days = cfg.get("max_days", 8)
    return BoardSpec(game_type="werewolf", ruleset=ruleset, roles=dict(expected),
                     wolf_meeting_rounds=int(rounds), max_days=int(days))


def _fmt_roles(roles: dict[str, int]) -> str:
    return "+".join(f"{n}{role}" for role, n in roles.items())


def validate_board(cfg: dict[str, Any], ruleset: str) -> BoardSpec:
    if ruleset == "standard-12":
        return validate_board_standard(cfg)
    if ruleset == "standard-9":
        return validate_board_standard9(cfg)
    return validate_board_minimal(cfg)


# ---------- 发牌 ----------

def deal_roles(spec: BoardSpec, rng: Random, player_count: int | None = None) -> list[RoleAssignment]:
    """把角色列表洗牌后按座位 1..n 分配（同种子可复现）。"""
    n = player_count if player_count is not None else spec.player_count
    bag = spec.role_list
    if len(bag) != n:
        raise ValueError(f"角色总数 {len(bag)} 与人数 {n} 不符")
    rng.shuffle(bag)
    return [RoleAssignment(seat=i + 1, role=role) for i, role in enumerate(bag)]


# ---------- 计票 ----------

def tally_votes(votes: dict[int, int], sheriff: int | None = None) -> dict[str, Any]:
    """计票。votes: voter_seat -> target_seat(0=弃权)。警长票权重 2。

    返回 {"exiled": seat|None, "tie": bool}。0 或缺失不计票。
    """
    weights: dict[int, int] = {}
    for voter, target in votes.items():
        if not target:
            continue
        w = 2 if (sheriff is not None and voter == sheriff) else 1
        weights[target] = weights.get(target, 0) + w
    if not weights:
        return {"exiled": None, "tie": True}
    top = max(weights.values())
    leaders = [t for t, c in weights.items() if c == top]
    if len(leaders) > 1:
        return {"exiled": None, "tie": True}
    return {"exiled": leaders[0], "tie": False}


# ---------- 定刀多数决 ----------

def decide_kill(
    proposals: dict[int, int], rng: Random, valid_targets: set[int] | None = None
) -> tuple[int | None, str]:
    """狼队收刀：并行提案多数决。

    proposals: wolf_seat -> target_seat(0=弃权)。
    返回 (target, decided_by)：decided_by ∈ majority / tie_rng / empty。
    平票用 rng 决出（结果由调用方写入事件）；无合规提案 = 空刀。
    """
    counts: dict[int, int] = {}
    for wolf, target in proposals.items():
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


# ---------- 夜间结算矩阵 ----------

def resolve_night(night: dict[str, Any]) -> dict[str, Any]:
    """夜间结算。输入 kill/guard/saved/poison，输出 deaths: seat -> death_cause。

    矩阵（docs/games/werewolf.md）：
    - 毒不被守卫/解药挡；同守同救=悖论死（刀杀）；同刀同毒=死因刀杀；空刀无人死于刀。
    """
    kill = night.get("kill")
    guard = night.get("guard")
    saved = bool(night.get("saved"))
    poison = night.get("poison")

    deaths: dict[int, str] = {}
    if poison is not None:
        deaths[poison] = ROLE_DEATH_BY_POISON
    if kill is not None:
        guarded = (guard == kill)
        if guarded and saved:
            # 守卫悖论死：救药与守护冲突致死，毒死因优先（毒不被任何手段改变）
            if kill not in deaths:
                deaths[kill] = ROLE_DEATH_BY_KNIFE
        elif guarded or saved:
            pass  # 守卫成功或被救活
        else:
            # 裸刀死；同刀同毒按「狼杀 > 女巫毒」优先级认定刀杀（可开枪）
            deaths[kill] = ROLE_DEATH_BY_KNIFE
    return {"deaths": deaths}


# ---------- 胜负 ----------

def _alive_count(roles: dict[int, str], alive: dict[int, bool], predicate) -> int:
    return sum(1 for s, r in roles.items() if alive.get(s) and predicate(r))


def check_winner_minimal(
    roles: dict[int, str], alive: dict[int, bool], day: int = 1, max_days: int = 8
) -> GameResult | None:
    """minimal：好人胜=狼全灭；狼胜=存活狼≥存活好人；day>max_days 狼胜。"""
    wolves = _alive_count(roles, alive, lambda r: r in WOLF_ROLES)
    goods = _alive_count(roles, alive, lambda r: r not in WOLF_ROLES)
    if wolves == 0:
        return GameResult(winner="good", reason="狼人全部出局")
    if wolves >= goods:
        return GameResult(winner="wolf", reason=f"存活狼 {wolves} ≥ 存活好人 {goods}")
    if day >= max_days:
        return GameResult(winner="wolf", reason=f"第 {max_days} 天结束仍有狼存活")
    return None


def check_winner_standard(
    roles: dict[int, str], alive: dict[int, bool], day: int = 1, max_days: int = 8
) -> GameResult | None:
    """standard-12：狼胜四路径（神职屠边/平民屠边/屠城/时限）；好人胜=狼全灭。"""
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
    if day >= max_days:
        return GameResult(winner="wolf", reason=f"第 {max_days} 天结束仍有狼存活")
    return None


def check_winner(ruleset: str, roles: dict[int, str], alive: dict[int, bool],
                 day: int = 1, max_days: int = 8) -> GameResult | None:
    # standard-9 与 standard-12 同走屠边+屠城+时限；minimal 走屠城+时限
    if ruleset.startswith("standard"):
        return check_winner_standard(roles, alive, day, max_days)
    return check_winner_minimal(roles, alive, day, max_days)
