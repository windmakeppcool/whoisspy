"""事件与通用数据模型（docs/backend/03-events.md）。

事件流是唯一事实源；可见性在 flow emit 时显式标注并随事件落库，
出站（导出/终端）只按库里的可见性过滤。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Vis:
    """事件可见性：public（全员）/ seat（仅成员）/ god（仅上帝视角）。"""

    level: str  # "public" | "seat" | "god"
    seats: list[int] = field(default_factory=list)


def public() -> Vis:
    """全员可见。"""
    return Vis(level="public")


def god() -> Vis:
    """上帝视角可见（夜晚操作/独白/诊断事件）。"""
    return Vis(level="god")


def seat(n: int) -> Vis:
    """仅指定座位可见。"""
    return Vis(level="seat", seats=[n])


@dataclass
class Event:
    """一条对局事件（seq 由单写者分配，从 1 起严格递增）。"""

    seq: int
    type: str
    day_index: int
    phase: str
    payload: dict[str, Any] = field(default_factory=dict)
    vis: Vis = field(default_factory=public)


@dataclass
class GameResult:
    """胜负结果（match.finished 的 payload 来源）。"""

    winner: str  # "wolf" | "good"
    reason: str


@dataclass
class AskSpec:
    """一次 agent 调用的规格（docs/backend/07-agent.md）。

    定义在通用模型层（而非 agent.py）：rules.validate_action 需要消费它，
    避免 agent ↔ rules 循环依赖。
    """

    action_type: str  # 期望动作类型（kill/check/save/vote/speech/register/...）
    prompt: str  # 指令文本（prompts.py 模板）
    prompt_extra: str = ""  # 附加语义（女巫刀口句等），落指令层
    candidates: list[int] = field(default_factory=list)  # 合法目标（进 prompt 与校验）