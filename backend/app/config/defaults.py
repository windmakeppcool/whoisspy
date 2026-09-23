"""选手档案与接入预设样例配置（data 目录被 .gitignore 忽略，此处提供程序内默认）。

真实部署时后端可从 backend/data/*.json 读取覆盖；测试与 --mock 使用这些默认值。
"""

from __future__ import annotations

DEFAULT_PERSONAS: list[dict[str, str]] = [
    {"id": "aggressive-liar", "name": "悍跳强攻型",
     "style": "语气强硬、短句、爱用反问；被质疑时提高音量重复结论。",
     "strategy": "拿狼必悍跳预言家，首夜就起跳；被围剿时反踩最沉默的人。"},
    {"id": "calm-analyst", "name": "冷静盘逻辑型",
     "style": "条理清晰、分点陈述、克制不情绪化。",
     "strategy": "优先盘票型与刀型；信息不足时明说不确定；发现悍跳会用证据链拆解。"},
    {"id": "actor", "name": "戏精表演型",
     "style": "夸张、有感染力、爱用比喻和排比。",
     "strategy": "制造话题转移火力；好人时勇猛，狼人时影帝级伪装。"},
    {"id": "direct", "name": "直球选手",
     "style": "简短直接、不绕弯、口语化。",
     "strategy": "有怀疑直接说出来；投票果断；不做复杂伪装。"},
    {"id": "quiet-observer", "name": "寡言观察型",
     "style": "惜字如金、只在关键时发言。",
     "strategy": "前期少说多记；关键轮给出致命一击的观察。"},
    {"id": "warm-keeper", "name": "温和照顾型",
     "style": "语气柔和、爱鼓励他人。",
     "strategy": "组织好人阵营信息共享；被怀疑时示弱博同情。"},
]

DEFAULT_PROVIDERS: list[dict] = [
    {"id": "mock", "base_url": "", "api_key_env": "", "currency": "CNY",
     "models": [{"id": "mock", "price_per_mtok_in": 0, "price_per_mtok_out": 0}]},
]
