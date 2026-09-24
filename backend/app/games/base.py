"""游戏插件契约中枢：新游戏只需实现 GameDefinition + 注册 + 规则切片 + boards 预设。

契约见 docs/game-plugin.md。engine/agents/storage 不为具体游戏改动：
- engine 通过 StepContext 暴露 IO 原语（发事件/问 agent/发言/收票）；
- 游戏的全部流程与结算写在 games/<name>/flow.py（GameDefinition.play）。

注意 Protocol 里出现的 StepContext 是「引擎实现、插件消费」的方向，插件不需要实现它。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from random import Random
from typing import Any, Protocol, runtime_checkable

from app.core import (
    ActionRequest,
    BoardSpec,
    Event,
    GameResult,
    RoleAssignment,
    VisMeta,
)


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


# Step：引擎执行单元。kind 由游戏插件定义（engine 不认识具体值），
# params 由插件自用（如发言顺序、投票候选）。
@dataclass
class Step:
    kind: str
    params: dict[str, Any] = field(default_factory=dict)


class StepContext(Protocol):
    """引擎提供给插件的步内原语（实现：app/engine/context.py）。"""

    step: Step

    @property
    def state(self) -> GameState: ...

    @property
    def spec(self) -> BoardSpec: ...

    @property
    def rng(self) -> Random: ...

    async def emit(self, etype: str, payload: dict[str, Any] | None = None,
                   vis: VisMeta | None = None) -> Event: ...

    async def monologue(self, seat: int, resp: dict[str, Any]) -> None: ...

    async def ask(self, seat: int, request: ActionRequest, purpose: str = "action",
                  step: Step | None = None) -> tuple[dict[str, Any], dict[str, Any]]: ...

    async def ask_many(self, seats: list[int], request: ActionRequest,
                       purpose: str = "action",
                       step: Step | None = None) -> dict[int, tuple[dict[str, Any],
                                                                    dict[str, Any]]]: ...

    async def speech(self, seat: int, request: ActionRequest, *, channel: bool = False,
                     purpose: str = "speech", step: Step | None = None) -> dict[str, Any]: ...

    async def collect_ballot(self, voters: list[int], candidates: list[int], *,
                             title: str = "投票", step_kind: str = "ballot",
                             purpose: str = "vote") -> dict[int, int]: ...


@runtime_checkable
class GameDefinition(Protocol):
    game_type: str

    # 配置与发牌
    def validate_board(self, board_cfg: dict[str, Any]) -> BoardSpec: ...
    def deal(self, spec: BoardSpec, rng: Random) -> list[RoleAssignment]: ...
    def initial_state(self, spec: BoardSpec, roles: list[RoleAssignment]) -> GameState: ...

    # 状态机（支柱 1 Reducer）
    def next_step(self, state: GameState) -> Step: ...
    def apply(self, state: GameState, event: Event) -> None: ...

    # 动作与规则
    def action_schema(self, state: GameState, step: Step) -> ActionRequest | None: ...
    def validate_action(self, state: GameState, step: Step, seat: int,
                        action: dict[str, Any]) -> dict[str, Any]: ...
    def neutral_action(self, state: GameState, step: Step) -> dict[str, Any]: ...
    def check_winner(self, state: GameState) -> GameResult | None: ...

    # 可见性唯一权威（支柱 3）
    def visibility(self, event: Event, state: GameState) -> VisMeta: ...

    # 规则切片注入（D12）
    def rule_slices(self) -> dict[str, str]: ...
    def slices_for(self, step: Step) -> list[str]: ...

    # 步内流程（游戏规则唯一归属地，engine 只提供 StepContext 原语）
    async def play(self, ctx: StepContext, step: Step) -> None: ...

    # 记忆层投影与阶段天数（engine 不认识的语义交给插件）
    def memory_line(self, event: Event) -> str | None: ...
    def phase_day(self, state: GameState, step: Step) -> int: ...
