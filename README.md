# whoisspy 设计文档

多 AI 合作对抗观赏台：多个 LLM 驱动的 AI 玩家进行「阵营制 + 隐藏身份」类对抗游戏（狼人杀首发），人只作为观众**边跑边追更**、翻看历史对局。架构按游戏插件扩展，后续可加谁是卧底、阿瓦隆等。

> **⚠ 后端重写进行中（D29，2026-09-25）**：旧后端将整体删除，重建为单进程 headless 对局引擎
> （只做游戏流程 + 记录 + 导出）。新设计规格见 **[backend/](backend/00-overview.md)**（00–14 共 15 份，
> 文档先行、待批准实施，落地顺序见 [backend/14-migration.md](backend/14-migration.md)）。
> 下表中旧后端域文档（architecture/engine/game-plugin/events-storage/agents-and-llm/configuration/api/milestones）
> **将在实施时退役**，由 docs/backend/ 对应文档取代；游戏规则书 [games/werewolf.md](games/werewolf.md) 收缩保留。

## 文档地图（按功能域拆分）

### 后端重写规格（目标态，docs/backend/）

| 文档 | 内容 |
|---|---|
| [backend/00-overview.md](backend/00-overview.md) | 目标/非目标、设计原则、保留与丢弃清单、旧→新模块对照 |
| [backend/01-structure.md](backend/01-structure.md) | 模块划分、依赖方向、技术选型、MatchRun 原语 |
| [backend/02-flow.md](backend/02-flow.md) | 一局完整流程规格（夜/昼/警长/死亡链/终止） |
| [backend/03-events.md](backend/03-events.md) | 事件目录：payload/可见性/触发时机/阶段 label |
| [backend/04-state.md](backend/04-state.md) | 类型化 GameState 与 reducer 规则 |
| [backend/05-rules.md](backend/05-rules.md) | 纯函数规则：发牌/定刀/计票/夜结算/胜负/动作校验 |
| [backend/06-prompts.md](backend/06-prompts.md) | prompt 六层、规则切片、指令模板、记忆行、围栏 |
| [backend/07-agent.md](backend/07-agent.md) | 调用协议：JSON 解析链、三层失败记账、中性兜底 |
| [backend/08-llm.md](backend/08-llm.md) | 网关：mock/真实、重试、计量计费、trace |
| [backend/09-config.md](backend/09-config.md) | providers/personas/.env、座位接入构建、密钥安全 |
| [backend/10-storage.md](backend/10-storage.md) | SQLite 表结构、seq 分配、store 函数集 |
| [backend/11-export.md](backend/11-export.md) | 观赛文案表（present 唯一权威）、导出 JSON schema |
| [backend/12-cli.md](backend/12-cli.md) | 命令行入口、stdout 直播、退出码 |
| [backend/13-testing.md](backend/13-testing.md) | 测试策略与验收基线（TDD） |
| [backend/14-migration.md](backend/14-migration.md) | 删除清单、落地提交序列、前端处置 |

### 现行文档（描述旧实现，实施时按 14-migration 退役/收缩）

| 文档 | 内容 | 什么时候动它 |
|---|---|---|
| [architecture.md](architecture.md) | 定位、四条设计支柱、分层与目录结构 | 引入新分层/新支柱 |
| [agents-and-llm.md](agents-and-llm.md) | Agent 座位级接入配置、人设与策略、Prompt 分层拼装契约、LLM 网关与用量计量 | 加 prompt 层、改计费/接入方式 |
| [game-plugin.md](game-plugin.md) | 多游戏插件契约：GameDefinition、Step 原语、rules 切片注入 | 改插件契约、加 Step 原语 |
| [games/werewolf.md](games/werewolf.md) | 狼人杀：规则范围、状态机、板子、狼队夜聊 | 改狼人杀规则 |
| [events-storage.md](events-storage.md) | 事件模型、可见性、存储表、SSE 契约、Reducer | 加事件类型、改表结构 |
| [engine.md](engine.md) | MatchRunner、步进循环、并发、容错链 | 改调度/容错策略 |
| [frontend.md](frontend.md) | 前端路由、组件、事件投影、SSE 消费 | 加页面/组件 |
| [frontend-design.md](frontend-design.md) | 视觉设计规范（唯一权威）：配色/字体/布局/组件形态；展示成品 design/showcase.html | 改视觉（先改此文档） |
| [configuration.md](configuration.md) | 配置文件规范与密钥安全 | 加/改配置项 |
| [api.md](api.md) | REST + SSE API 契约 | 加/改端点 |
| [milestones.md](milestones.md) | 里程碑、验收标准、测试策略 | 里程碑完成、验收标准变更 |
| [decisions.md](decisions.md) | 关键决策记录（背景、决策、备选、影响） | **任何设计决策变更时追加条目** |
| [roadmap.md](roadmap.md) | 暂缓项与后续方向 | 某项启动时移入对应文档展开 |

## 运行入口

- API 服务：`python -m app.main [--port N]`（uvicorn）。
- TUI 观看器：`python -m app.main --tui [--match-id N] [--port N]`——同进程拉起 API 并打开终端观看视图，与 Web 前端共用同一套 REST/SSE（契约见 [api.md](api.md)，决策见 [decisions.md](decisions.md) D16）。

## 扩展约定（方便后续按功能扩展）

- **新增游戏**：新建 `docs/games/<name>.md` 写规则范围/状态机/提示词切片；代码侧实现 `GameDefinition` + 注册 + prompts + boards 预设 + 测试。engine / agents / storage 不应为新游戏改动——如果必须改，说明插件契约有缺口，**先改 game-plugin.md 再动代码**。
- **新增功能**（如播放控制、分叉重跑）：在归属文档加章节；跨域的新建 `<feature>.md` 并在上表登记；同时在 roadmap.md 勾销。
- **决策变更**：decisions.md 追加新条目（编号递增，注明日期、推翻了哪条旧决策），旧条目保留不删改。
- 全部中文撰写，代码标识符与命令保留原文。
