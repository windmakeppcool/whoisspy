# CLAUDE.md

多 AI 合作对抗观赏台：LLM 驱动的 AI 玩家打隐藏身份对抗游戏（狼人杀首发）。
后端为单进程 **headless 对局引擎**（D29）：跑一局标准 9 人狼人杀 + 事件落库 + 对话导出；
前端因后端重写暂不可用（代码保留）。

设计文档在 `docs/`（长期维护，按功能域拆分），细节以文档为准：

- 后端规格（唯一权威）：[docs/backend/00-overview.md](docs/backend/00-overview.md)（00–14 分册：
  结构/流程/事件/状态/规则/prompt/agent/llm/配置/存储/导出/CLI/测试/落地记录）
- 游戏规则书：[docs/games/werewolf.md](docs/games/werewolf.md)（规则口径唯一权威）
- 前端/视觉/路线图：[docs/frontend.md](docs/frontend.md) · [docs/frontend-design.md](docs/frontend-design.md) · [docs/roadmap.md](docs/roadmap.md)

## 开发规则

1. 始终用中文交流与写注释。
2. TDD 铁律：先写失败测试再写实现（配置文件豁免）；测试策略与验收见 [docs/backend/13-testing.md](docs/backend/13-testing.md)。
3. Python 遵循 PEP 8 + Type Hints + 4 空格缩进。
4. 安全：绝不硬编码密钥、杜绝 SQL 注入；API key 只经 `api_key_env` 环境变量注入（不进配置/不落库/不进日志/trace），座位 `base_url` 必须在 providers.json 白名单内；他人发言进 prompt 必须围栏包裹并声明禁读。
5. 配置文件一律 JSON（providers/personas，放 `backend/data/`，不入 git）；**板子是代码常量**（standard-9，`rules.py`），无 boards.json（D32）。
6. 模块边界：游戏语义只准出现在 `backend/app` 的 `rules/prompts/memory/present/flow`；`events/state` 只做通用模型；`store/llm/config` 无游戏语义（依赖方向见 [docs/backend/01-structure.md](docs/backend/01-structure.md)）。
7. 设计决策变更 → 在 [docs/decisions.md](docs/decisions.md) 追加条目（不删改旧条目）。