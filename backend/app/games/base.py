"""游戏插件契约中枢：新游戏只需实现 GameDefinition + 注册 + 规则切片 + boards 预设。

契约见 docs/game-plugin.md。engine/agents/storage 不为具体游戏改动。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from random import Random
from typing import Any, Protocol, runtime_checkable

from app.core import ActionRequest, BoardSpec, Event, GameResult, RoleAssignment, VisMeta


@dataclass
class GameState:
    """可变对局状态，只能由 apply 逐事件归约修改。"""

    spec: BoardSpec
    roles: dict[int, str]  # seat -> role
    alive: dict[int, bool]
    day: int = 0
    phase: str = "init"
    winner: GameResult | None = None
    extra: dict[str, Any] = field(default_factory=dict)  # 游戏私有状态（女巫药、警徽等）


# Step：引擎执行单元。原语四件套定义在 engine/steps.py，游戏插件经 next_step 产出。
@dataclass
class Step:
    kind: str  # channel_meeting / solo_action / serial_speech / ballot / resolve / noop
    params: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class GameDefinition(Protocol):
    game_type: str

    def validate_board(self, board_cfg: dict[str, Any]) -> BoardSpec: ...
    def deal(self, spec: BoardSpec, rng: Random) -> list[RoleAssignment]: ...
    def initial_state(self, spec: BoardSpec, roles: list[RoleAssignment]) -> GameState: ...
    def next_step(self, state: GameState) -> Step: ...
    def apply(self, state: GameState, event: Event) -> None: ...
    def action_schema(self, state: GameState, step: Step) -> ActionRequest | None: ...
    def validate_action(self, state: GameState, seat: int, action: dict[str, Any]) -> dict[str, Any]: ...
    def check_winner(self, state: GameState) -> GameResult | None: ...
    def visibility(self, event: Event, state: GameState) -> VisMeta: ...
    def rule_slices(self) -> dict[str, str]: ...
    def slices_for(self, step: Step) -> list[str]: ...
