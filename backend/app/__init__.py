"""whoisspy headless 对局引擎（D29 重写）。

跑一局标准 9 人狼人杀（mock 或真实 LLM）→ 事件落 SQLite → 导出对话 JSON。
入口：python -m app.main（见 backend/12-cli.md）。
"""

__version__ = "0.2.0"