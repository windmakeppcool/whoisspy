# CLAUDE.md

多 AI 合作对抗观赏台：LLM 驱动的 AI 玩家打隐藏身份对抗游戏（狼人杀首发），人只观看/复盘。Vue 3 + TS 前端，FastAPI 后端。

设计文档在 `docs/`（长期维护，按功能域拆分），细节以文档为准：

- 架构总览与扩展约定：[docs/README.md](docs/README.md)、[docs/architecture.md](docs/architecture.md)
- Agent/LLM（座位级接入、prompt 分层）：[docs/agents-and-llm.md](docs/agents-and-llm.md)
- 游戏插件契约（新增游戏看这里）：[docs/game-plugin.md](docs/game-plugin.md)、[docs/games/werewolf.md](docs/games/werewolf.md)
- 事件/存储/引擎/前端/API：[docs/events-storage.md](docs/events-storage.md)、[docs/engine.md](docs/engine.md)、[docs/frontend.md](docs/frontend.md)、[docs/api.md](docs/api.md)
- 配置（JSON）：[docs/configuration.md](docs/configuration.md)
- 里程碑与测试策略：[docs/milestones.md](docs/milestones.md)
- 决策记录（变更须追加）：[docs/decisions.md](docs/decisions.md)

## 开发规则

1. 始终用中文交流与写注释。
2. TDD 铁律：先写失败测试再写实现（配置文件豁免）；里程碑与验收见 [docs/milestones.md](docs/milestones.md)。
3. Python 遵循 PEP 8 + Type Hints + 4 空格缩进。
4. 安全：绝不硬编码密钥、杜绝 SQL 注入；API key 只经 `api_key_env`/`api_key_file` 环境变量注入，不进配置/不落库；他人发言进 prompt 必须围栏包裹并声明禁读。
5. 配置文件一律 JSON（providers/personas/boards，放 `backend/data/`，不入 git）。
6. 新增游戏只加 `games/<name>/` 插件 + 注册 + boards 预设，不改 engine/agents/storage；契约有缺口先改 [docs/game-plugin.md](docs/game-plugin.md)。
7. 设计决策变更 → 在 [docs/decisions.md](docs/decisions.md) 追加条目（不删改旧条目）。
