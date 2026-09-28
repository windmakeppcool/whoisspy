# 01 模块结构与技术选型

## 一、目录结构

```
backend/
  pyproject.toml          # 依赖收敛（见第三节）
  data/                   # .gitignore：providers.json personas.json .env whoisspy.db
  exports/                # .gitignore：导出的对话 JSON（默认输出目录）
  app/
    main.py               # CLI 入口：参数解析、装配、跑局、导出（[12-cli.md](12-cli.md)）
    config.py             # providers/personas/.env 加载与校验、座位接入构建（[09-config.md](09-config.md)）
    llm.py                # LLM 网关：mock + 真实（openai SDK）、重试、计量、trace（[08-llm.md](08-llm.md)）
    agent.py              # 座位 agent：六层 prompt 拼装、JSON 协议解析链、动作校验入口（[07-agent.md](07-agent.md)）
    memory.py             # 事件 → 座位记忆行（agent 记忆层唯一渲染，含围栏）（[06-prompts.md](06-prompts.md)）
    prompts.py            # 规则切片文本 + 各动作指令模板（游戏知识，静态可查）（[06-prompts.md](06-prompts.md)）
    events.py             # Event/Vis dataclass、可见性构造器、事件类型常量（[03-events.md](03-events.md)）
    state.py              # GameState（类型化字段）+ apply() reducer（[04-state.md](04-state.md)）
    rules.py              # 纯函数规则：板子常量/发牌/计票/定刀/夜结算/胜负/动作校验（[05-rules.md](05-rules.md)）
    flow.py               # ★ 一局完整流程（直排 async 代码）+ MatchRun 原语（[02-flow.md](02-flow.md)）
    present.py            # 事件 → 观赛文案行（导出与终端直播唯一投影）（[11-export.md](11-export.md)）
    store.py              # SQLite 读写：match/match_seat/game_event/llm_call（[10-storage.md](10-storage.md)）
    export.py             # 事件 → 分段对话 JSON（view 过滤 + present 渲染）（[11-export.md](11-export.md)）
  tests/                  # 见 [13-testing.md](13-testing.md)
```

**平铺、不建包**：13 个模块各管一件事，`grep`/IDE 全局可搜。
唯一的「厚」模块是 `flow.py`（预计 400–500 行），它厚是应该的——一局的编排本来就长，
宁可一个文件读到底，也不要把流程切碎藏进抽象。

## 二、依赖方向（无环，测试友好）

```
main ──► config ──► (llm | agent)          main ──► flow ──► export ──► present
flow ──► agent ──► llm                      flow ──► state / rules / events / prompts / memory / store
agent ──► memory / prompts / events / rules
export ──► present / events
store、llm ──►（各自 IO 边界，互不依赖）
```

硬性规则：

1. `rules / state / events / memory / present / prompts` **零 IO、零框架依赖**——纯函数/纯数据，
   不 import `flow/agent/llm/store/config/main` 中的任何一个（单测不需要任何夹具）。
2. `agent` 只依赖 `llm` 的接口与纯模块；`flow` 是唯一「什么都认识」的编排层。
3. `store.py` 不知道任何游戏语义（表结构见 [10-storage.md](10-storage.md)）；
   游戏语义只能出现在 `rules/prompts/memory/present/flow`。
4. 不写 Protocol/ABC 间接层：`flow` 直接调用 `agent.ask`、`agent` 直接调用 `llm.complete`。
   测试注入用普通参数（传入假的 `complete` 函数或假 seat 配置 `model="mock"`），不需要接口类型。

## 三、技术选型

| 项 | 选择 | 理由 |
|---|---|---|
| 运行时 | Python 3.11+，asyncio | 并行收票/并行收刀需要并发；沿用现有生态 |
| LLM 调用 | `openai` SDK（OpenAI 兼容协议，D5） | 各家端点兼容面最大；重试/超时语义已在规格中固化 |
| 配置校验 | `pydantic` | providers/personas 的 JSON 校验（沿用） |
| 存储 | `aiosqlite`（裸用，**去 SQLModel/SQLAlchemy**） | 4 张表 6 个查询；DDL 与 SQL 直接可读、可打印、可解释 |
| 测试 | `pytest` + `pytest-asyncio`（`asyncio_mode = "auto"` 沿用） | TDD 铁律不变 |
| 删除依赖 | `fastapi` `uvicorn` `sqlmodel` `sqlalchemy` `textual` | 无 HTTP、无 ORM、无 TUI |

`pyproject.toml` 目标形态：

```toml
dependencies = ["aiosqlite>=0.20", "openai>=1.40", "pydantic>=2.7"]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23"]
```

## 四、MatchRun：一局的显式上下文

`flow.py` 定义唯一的上下文对象，流程函数都以它为第一参数：

```python
@dataclass
class MatchRun:
    match_id: int
    seed: int
    state: GameState          # 唯一权威状态（只由 apply 修改）
    seats: dict[int, SeatCfg]  # 座位快照：persona/style/strategy/model/base_url/key/单价
    gateway: LLMGateway        # llm.py 的实例（mock 或真实）
    rng: Random               # 对局级随机源（种子=seed）
    emit: ...                  # 原语见下
```

它提供 4 个原语（旧 StepContext 的直译，但无 Protocol、无插件语义）：

| 原语 | 行为 |
|---|---|
| `await emit(type, payload, vis=public())` | 落事件（seq=上一条+1，单写者）→ 立即 `state.apply` → 追加内存事件表 → trace |
| `await ask(seat, spec, purpose)` | 组 prompt（六层）→ 网关 → 解析/修复/校验 → 必要时中性兜底；返回 `(action, reply, fell_back)` |
| `await speak(seat, spec, purpose)` | `ask` + 落 `player.speech`（240 字截断）+ 落独白 |
| `await ballot(voters, candidates, title, purpose)` | **并行**问票、**按座位升序**逐个落 `vote.cast`+独白（P3 确定性）；返回 `voter→target` |

流程函数形态（详见 [02-flow.md](02-flow.md)）：

```python
async def run_match(run: MatchRun) -> GameResult | None: ...
async def night_phase(run) -> None: ...
async def sheriff_election(run) -> None: ...
async def day_phase(run) -> None: ...
async def resolve_deaths(run, causes: dict[int, str]) -> None: ...
```
