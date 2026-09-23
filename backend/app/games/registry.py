"""游戏注册表：game_type(+ruleset) → GameDefinition 实例。"""

from __future__ import annotations

from typing import Any

from app.games.base import GameDefinition
from app.games.werewolf.definition import WerewolfGame

_REGISTRY: dict[str, type] = {"werewolf": WerewolfGame}

PRESETS: dict[str, dict[str, Any]] = {
    "p6-classic": {"game_type": "werewolf", "ruleset": "minimal",
                   "roles": {"wolf": 2, "seer": 1, "villager": 3},
                   "wolf_meeting_rounds": 2, "max_days": 8},
    "p8-classic": {"game_type": "werewolf", "ruleset": "minimal",
                   "roles": {"wolf": 2, "seer": 1, "villager": 5},
                   "wolf_meeting_rounds": 2, "max_days": 8},
    "p10-no-seer": {"game_type": "werewolf", "ruleset": "minimal",
                    "roles": {"wolf": 3, "villager": 7},
                    "wolf_meeting_rounds": 2, "max_days": 8},
    "p12-standard": {"game_type": "werewolf", "ruleset": "standard-12",
                     "roles": {"wolf": 3, "wolf_king": 1, "seer": 1, "witch": 1,
                               "hunter": 1, "guard": 1, "villager": 4},
                     "wolf_meeting_rounds": 2, "max_days": 8},
}


def create_game(game_type: str, ruleset: str) -> GameDefinition:
    cls = _REGISTRY.get(game_type)
    if cls is None:
        raise ValueError(f"未注册的游戏类型: {game_type}")
    return cls(ruleset=ruleset)  # type: ignore[return-value]


def resolve_board(board_cfg: dict[str, Any]) -> tuple[GameDefinition, BoardSpec]:
    """按 id 预设或 custom roles 解析出 (game, spec)。"""
    cfg = dict(board_cfg)
    if "id" in cfg and cfg["id"] in PRESETS:
        cfg = {**PRESETS[cfg["id"]], **{k: v for k, v in cfg.items() if k != "id"}}
    game_type = cfg.get("game_type", "werewolf")
    ruleset = cfg.get("ruleset", "minimal")
    game = create_game(game_type, ruleset)
    spec = game.validate_board(cfg)
    return game, spec
