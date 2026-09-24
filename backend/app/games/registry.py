"""游戏注册表：game_type → GameDefinition 实例；板子预设（当前唯一：p9-standard）。

单板收敛（D23）：板子越少，出错面越小。新增板子前请先读 docs/game-plugin.md 与 docs/decisions.md。
"""

from __future__ import annotations

from typing import Any

from app.core import BoardSpec
from app.games.base import GameDefinition
from app.games.werewolf import rules as wr
from app.games.werewolf.definition import WerewolfGame

_REGISTRY: dict[str, type] = {"werewolf": WerewolfGame}

DEFAULT_BOARD_ID = "p9-standard"

PRESETS: dict[str, dict[str, Any]] = {
    DEFAULT_BOARD_ID: {
        "game_type": "werewolf",
        "ruleset": wr.RULESET,
        "roles": dict(wr.STANDARD9_ROLES),
        "wolf_meeting_rounds": 2,
        "max_days": 8,
    },
}


def create_game(game_type: str) -> GameDefinition:
    """按 game_type 实例化插件；未注册直接拒绝。"""
    cls = _REGISTRY.get(game_type)
    if cls is None:
        raise ValueError(f"未注册的游戏类型: {game_type}")
    game: GameDefinition = cls()
    return game


def resolve_board(board_cfg: dict[str, Any]) -> tuple[GameDefinition, BoardSpec]:
    """按预设 id 或显式 roles 解析出 (game, spec)；未知板子直接拒绝。"""
    cfg = dict(board_cfg)
    board_id = cfg.pop("id", None)
    if board_id is not None:
        preset = PRESETS.get(board_id)
        if preset is None:
            raise ValueError(f"未知板子 {board_id!r}，当前仅支持 {sorted(PRESETS)}")
        cfg = {**preset, **cfg}
    game = create_game(cfg.get("game_type", "werewolf"))
    return game, game.validate_board(cfg)
