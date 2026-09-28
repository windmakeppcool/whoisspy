# whoisspy 设计文档

多 AI 合作对抗观赏台：多个 LLM 驱动的 AI 玩家进行「阵营制 + 隐藏身份」类对抗游戏（狼人杀首发）。
后端为**单进程 headless 对局引擎**（D29）：跑一局标准 9 人狼人杀（mock 或真实 LLM），
全程事件落 SQLite，跑完导出对话 JSON；人作为赛后读者翻看记录。

## 文档地图（按功能域拆分）

| 文档 | 内容 | 什么时候动它 |
|---|---|---|
| [backend/00-overview.md](backend/00-overview.md) | 后端总览：目标/非目标、设计原则、保留与丢弃清单 | 引入新设计原则 |
| [backend/01-structure.md](backend/01-structure.md) | 模块划分、依赖方向、技术选型、MatchRun 原语 | 加/改模块 |
| [backend/02-flow.md](backend/02-flow.md) | 对局流程规格（夜/昼/警长/死亡链/终止） | 改流程 |
| [backend/03-events.md](backend/03-events.md) | 事件目录：payload/可见性/触发时机/阶段 label | 加/改事件类型 |
| [backend/04-state.md](backend/04-state.md) | 类型化 GameState 与 reducer 规则 | 改状态/归约 |
| [backend/05-rules.md](backend/05-rules.md) | 纯函数规则：发牌/定刀/计票/夜结算/胜负/动作校验 | 改规则 |
| [backend/06-prompts.md](backend/06-prompts.md) | prompt 六层、规则切片、指令模板、记忆行、围栏 | 改 prompt |
| [backend/07-agent.md](backend/07-agent.md) | 调用协议：JSON 解析链、三层失败记账、中性兜底 | 改容错链 |
| [backend/08-llm.md](backend/08-llm.md) | 网关：mock/真实、重试、计量计费、trace | 改网关 |
| [backend/09-config.md](backend/09-config.md) | providers/personas/.env、座位接入构建、密钥安全 | 改配置 |
| [backend/10-storage.md](backend/10-storage.md) | SQLite 表结构、seq 分配、store 函数集 | 改存储 |
| [backend/11-export.md](backend/11-export.md) | 观赛文案（present 唯一权威）、导出 JSON schema | 改导出/文案 |
| [backend/12-cli.md](backend/12-cli.md) | 命令行入口、stdout 直播、退出码 | 改 CLI |
| [backend/13-testing.md](backend/13-testing.md) | 测试策略与验收基线（TDD） | 改测试策略 |
| [backend/14-migration.md](backend/14-migration.md) | 重写落地记录：删除清单、提交序列、前端处置 | 重写完成时归档 |
| [games/werewolf.md](games/werewolf.md) | 狼人杀**纯规则书**（规则口径唯一权威） | 改狼人杀规则 |
| [frontend.md](frontend.md) | 前端（重写期间暂不可用） | 重建最小 API 时 |
| [frontend-design.md](frontend-design.md) | 视觉设计规范（唯一权威）：配色/字体/布局/组件形态 | 改视觉 |
| [decisions.md](decisions.md) | 关键决策记录（背景、决策、备选、影响） | **任何设计决策变更时追加条目** |
| [roadmap.md](roadmap.md) | 暂缓项与后续方向 | 某项启动时移入对应文档展开 |

## 运行入口

```bash
cd backend
python -m app.main --mock --seed 42          # mock 跑一局（确定性）
python -m app.main --real [--model M]        # 真实 LLM 跑一局（需 providers.json + .env）
```

参数与输出形态见 [backend/12-cli.md](backend/12-cli.md)；配置见 [backend/09-config.md](backend/09-config.md)。

## 扩展约定

- **新增游戏/重建 API**：先读 [decisions.md](decisions.md) D32（不预设插件抽象），
  在对应功能域文档展开设计后追加决策条目。
- **决策变更**：decisions.md 追加新条目（编号递增，注明日期、推翻了哪条旧决策），旧条目保留不删改。
- 全部中文撰写，代码标识符与命令保留原文。