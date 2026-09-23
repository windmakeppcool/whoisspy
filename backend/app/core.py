"""游戏无关的核心类型：事件、动作、可见性、规格。

所有模块只依赖本模块与 games/base.py 的协议，不反向依赖具体游戏。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

# 可见性等级：public 所有人可见；seat 仅 vis_seats 中的座位可见；god 仅上帝视角可见
VisLevel = Literal["public", "seat", "god"]


@dataclass
class VisMeta:
    """事件的可见性元数据，出站过滤只认这份信息。"""

    level: VisLevel = "public"
    seats: list[int] = field(default_factory=list)


@dataclass
class Event:
    """内存中的游戏事件（入库前）。seq 由 MatchRunner 分配。"""

    type: str
    payload: dict[str, Any]
    day_index: int = 0
    phase: str = ""
    vis: VisMeta = field(default_factory=VisMeta)
    seq: int = 0  # 由 runner 在 append 时写入


def filtered_view(event: Event, view: str) -> Event | None:
    """按视角过滤事件：出站（REST/SSE）统一走这里。

    view="immersive" 只看 public；view="god" 全量。
    """
    if view == "god":
        return event
    if event.vis.level == "public":
        return event
    return None


@dataclass
class ActionRequest:
    """向 agent 请求的动作描述（action_schema 产出）。"""

    action_type: str  # speech / vote / kill / check / save / poison / guard / shoot / badge / pass
    candidates: list[int] = field(default_factory=list)  # 合法目标座位
    prompt: str = ""  # 步骤任务指令
    extra: dict[str, Any] = field(default_factory=dict)  # 复合动作的附加语义


@dataclass
class BoardSpec:
    """校验后的板子规格。"""

    game_type: str
    ruleset: str
    roles: dict[str, int]
    wolf_meeting_rounds: int = 2
    max_days: int = 8

    @property
    def player_count(self) -> int:
        return sum(self.roles.values())

    @property
    def role_list(self) -> list[str]:
        """展开为按座位分配的角色列表（洗牌前）。"""
        out: list[str] = []
        for role, n in self.roles.items():
            out.extend([role] * n)
        return out


@dataclass
class RoleAssignment:
    seat: int
    role: str


@dataclass
class GameResult:
    winner: Literal["wolf", "good"]
    reason: str
