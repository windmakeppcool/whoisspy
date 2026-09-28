# 00 总览：headless 对局引擎（重写规格）

> **状态**：本目录是后端推倒重写的**设计规格（文档先行，未实施）**。
> 现存旧后端代码将在实施时整体删除，落地顺序见 [14-migration.md](14-migration.md)。
> 决策依据：[decisions.md](../decisions.md) D29–D33。

## 一、定位

单进程、无 HTTP 的**对局引擎**：跑一局标准 9 人狼人杀（mock 或真实 LLM），
全程事件落 SQLite，跑完导出对话 JSON。人是「赛后读者」，不是实时观众——
这是本次重写的**全部范围**。

```
python -m app.main --mock --seed 42
  → 9 个 AI 玩家打完一局（终端逐行直播）
  → 事件全量落库（backend/data/whoisspy.db）
  → 导出复盘文件（exports/match-1-god.json）
```

## 二、目标与非目标

**目标**

1. 标准 9 人局流程完整正确（夜/昼/警长/枪/警徽/胜负全分支）；
2. 记录完备：事件流 + 每次模型调用的用量与费用；
3. 导出：一份可直接阅读/归档的对话 JSON（上帝/公开两种视角）；
4. mock 模式**确定性可复现**（同 seed → 逐字节相同的事件流）；
5. 代码**可单步调试**：流程是直排代码，没有协议跳转与运行时注册表。

**非目标（本次明确不做）**

- FastAPI / REST / SSE / WebSocket——前端暂不可用（处置见 [14-migration.md](14-migration.md)）；
- TUI 观看器（删除，不迁移）；
- 回放/分叉重跑工具（事件表天然支持，未来需要再加）;
- 多游戏插件抽象（GameDefinition / StepContext / registry 全部删除）；
- 并发多局（一次进程跑一局）。

## 三、设计原则（针对旧架构的病灶）

| # | 原则 | 针对的旧病灶 |
|---|---|---|
| P1 | **直排流程**：一局流程在 `flow.py` 里从头读到尾；每个阶段是一个普通 async 函数 | 引擎/插件经 Protocol 与 `StepContext` 互相间接、handler 按字符串注册在运行时 dict——调试时无法静态跳转，看不到「谁在驱动谁」 |
| P2 | **事件即记录**：append-only 事件流 + reducer 归约（保留旧架构最值钱的资产） | （旧架构已具备，保留）状态只能由 `apply(event)` 改 |
| P3 | **确定性**：rng 带种子且决策入事件；并行收票**按座位序落事件**；mock 同 seed 逐字节复现 | 并行 `gather` 完成序决定 `vote.cast` 落库顺序，真实局两轮重跑事件序不同，「重跑对比」调试法失效 |
| P4 | **每次调用留痕**：`llm_call` 记数字，`--trace` 记 prompt/响应原文，校验代码崩溃单独落 `rule.error` | 旧系统出问题后无法回看「当时 prompt 长什么样」；插件 bug 被记成「LLM 调用失败」 |
| P5 | **投影单一归属**：agent 记忆行只在 `memory.py`，观赛文案只在 `present.py`，导出与终端直播共用后者 | 同一份「事件→人话」逻辑写了 4 份（插件 memory_line / TUI viewmodel / 前端 project.ts / export dialog.py）且已漂移（守卫死代码、标签不一致、可见性客户端重复过滤） |
| P6 | **状态类型化**：`GameState` 全部具名字段，无 `extra` 私有字典，可整树打印 | 断点上看 `state.extra["last_exile_was_alive"]` 全靠脑内记忆字段语义 |

## 四、保留什么 / 丢弃什么

**保留的资产**（语义随迁，出处标注在各规格文档）：

| 资产 | 旧出处 | 新归属 |
|---|---|---|
| append-only 事件流 + reducer | 支柱 1 | [04-state.md](04-state.md) |
| 事件级可见性（public/seat/god）随事件落库 | 支柱 3 | [03-events.md](03-events.md) |
| 种子随机，随机决策写入事件 payload | 支柱 1 | [05-rules.md](05-rules.md) |
| prompt 六层拼装 + 前缀缓存层序 + 围栏防注入 | agents-and-llm.md | [06-prompts.md](06-prompts.md) |
| 输出 JSON 协议（monologue→speech→action 字段序） | D22 | [07-agent.md](07-agent.md) |
| 中性兜底（每动作类型的中性动作，绝不替玩家用药/开枪） | D25/S3 | [07-agent.md](07-agent.md) |
| LLM 网关重试语义（openai 异常族/退避/不重试 4xx）与计量计费 | agents-and-llm.md | [08-llm.md](08-llm.md) |
| 座位级接入快照（provider/persona/单价固化进库） | D10/D11/D18/D19 | [09-config.md](09-config.md) · [10-storage.md](10-storage.md) |
| 全部游戏规则语义（结算矩阵/警长流/死亡链/胜负） | games/werewolf.md | [02-flow.md](02-flow.md) · [05-rules.md](05-rules.md) |

**丢弃的包袱**（理由见 D32）：

| 丢弃 | 理由 |
|---|---|
| GameDefinition/StepContext/注册表/boards.json | 只有一个游戏；抽象层是纯成本（间接跳转、双重契约、架构测试锁边界） |
| engine 与 games 的拆分 | 游戏即代码：`flow.py` 直接 import `rules/state/agent` |
| FastAPI/SSE/TUI | 本次范围外；单进程 CLI 是最小正确形态 |
| SQLModel/SQLAlchemy | 4 张表 6 个查询，裸 `aiosqlite` + 手写 DDL 更短更透明 |
| `state.extra` 私有字典 | 类型化字段（P6） |
| 客户端/导出各自解释事件 | 投影单一归属（P5） |

## 五、模块与文档对照

模块划分见 [01-structure.md](01-structure.md)。每份规格对应一个（或一对）模块：

| 文档 | 模块 |
|---|---|
| [02-flow.md](02-flow.md) 流程规格 | `flow.py` |
| [03-events.md](03-events.md) 事件目录 | `events.py` |
| [04-state.md](04-state.md) 状态与 reducer | `state.py` |
| [05-rules.md](05-rules.md) 纯函数规则 | `rules.py` |
| [06-prompts.md](06-prompts.md) prompt 与记忆层 | `prompts.py` · `memory.py` |
| [07-agent.md](07-agent.md) 调用协议与兜底 | `agent.py` |
| [08-llm.md](08-llm.md) 网关与 trace | `llm.py` |
| [09-config.md](09-config.md) 配置与密钥 | `config.py` |
| [10-storage.md](10-storage.md) 存储 | `store.py` |
| [11-export.md](11-export.md) 导出与观赛文案 | `export.py` · `present.py` |
| [12-cli.md](12-cli.md) 命令行 | `main.py` |
| [13-testing.md](13-testing.md) 测试策略 | `tests/` |
| [14-migration.md](14-migration.md) 删除与落地 | — |

## 六、旧模块 → 新模块 对照（概念无丢失）

| 旧 | 新 |
|---|---|
| `engine/runner.py`（步进循环/容错链） | `flow.py`（直排循环 + 显式容错分支） |
| `engine/context.py`（StepContext 原语） | `flow.py::MatchRun`（emit/ask/speak 方法，无 Protocol） |
| `games/werewolf/definition.py`（next_step/apply/visibility/memory_line） | 拆进 `flow.py`（直排）+ `state.py`（apply）+ `memory.py`（记忆行）；可见性在 emit 时显式传 |
| `games/werewolf/rules.py` / `prompts.py` | `rules.py` / `prompts.py`（原样平移） |
| `agents/protocol.py` | `agent.py` + `memory.py` |
| `llm/gateway.py` | `llm.py`（+trace） |
| `storage/repo.py` + models | `store.py`（裸 aiosqlite） |
| `config/loader.py` | `config.py` |
| `api/app.py` + `main.py`（HTTP/TUI） | 删除；`main.py` 只做 CLI |
| `tui/` + `export/dialog.py` + 前端 `project.ts` 的游戏解释 | `present.py`（唯一观赛投影） |
