"""容错兜底：一切 agent 失败最终落到中性动作，绝不卡死整局（docs/engine.md）。

原则：兜底不替玩家做主——投票弃权、定刀空刀、验人不验、发言沉默。
"""

from __future__ import annotations

from app.core import ActionRequest


def fallback_action(request: ActionRequest, rng_seed: int = 0) -> dict:
    """按动作类型返回中性兜底动作。"""
    return {"type": request.action_type, "target": 0}
