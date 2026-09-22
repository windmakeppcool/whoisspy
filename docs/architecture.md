# 架构总览

## 定位

基于网页的「多 AI 合作对抗观赏台」：多个 LLM 驱动的 AI 玩家打隐藏身份对抗游戏（狼人杀首发），人只观看——实时追更（SSE）与历史复盘共用同一套渲染。核心卖点是**多模型混战**（每座位独立端点+模型+人设/策略）、**狼队夜间私密频道商量战术**、**结构化内心独白**（言行不一可见）。

技术栈：前端 Vue 3 + TypeScript（Vite、Pinia），后端 FastAPI（Python 3.11+），SQLModel + SQLite（aiosqlite），openai SDK（OpenAI 兼容接入），SSE 推送。

## 四条设计支柱

1. **Reducer 架构**：GameState 由 append-only 事件流逐条 `apply` 归约；随机数走带种子的 `Random` 且结果（含分布/决胜）写入事件 → 未来时间轴/分叉重跑不堵死。
2. **Step 原语组合**：游戏插件只编排 4 个原语（见 [game-plugin.md](game-plugin.md)）+ 结算规则；抽象仅覆盖「阵营制 + 隐藏身份 + 轮流发言 + 投票」这一族，不做万能引擎。
3. **可见性是事件元数据**（public / seat / god），服务端出站前统一过滤，前端永远拿不到当前视角外的数据。
4. **单局单写者**：MatchRunner 独占事件 append（seq 递增），SSE 以 seq 为游标断线补发。

## 分层与依赖方向

```
前端 Vue3+TS（Pinia + SSE 消费）
  对局列表 / 创建表单 / MatchView（观赛追更与历史详情共用 MatchStage 渲染）
        │ SSE 增量追新 + REST 回填
FastAPI：api/（matches / stream / catalog）
engine/ 对局运行核心（与游戏无关）
  MatchRunner（单局 = 单 asyncio task，步内可并行）
  Step 原语 ×4 ｜ faults 容错链 ｜ EventBroker（事件入库 + SSE 扇出）
games/ 插件层（GameDefinition 协议，rules 切片注入）   agents/（座位配置 + prompt 六层拼装 + JSON 协议）
llm/（OpenAI 兼容网关 + 重试 + token/费用计量）
storage/ Repository 抽象（SQLite 实现，append-only 事件表）
config/（YAML 加载校验；key 只走环境变量）
```

依赖规则（保持插件边界的关键）：

- `games/` 不 import `engine/` 内部实现，只依赖 `games/base.py` 的契约类型。
- `agents/` 不 import 具体游戏——prompt 拼装只消费 GameDefinition 暴露的规则切片接口。
- `storage/` 无业务语义，只做持久化；`api/` 不写事件，事件一律经 MatchRunner（单局单写者）。
- 新增游戏不改 engine / agents / storage；若必须改，先改 [game-plugin.md](game-plugin.md) 契约再动代码。

## 目录结构（关键文件）

```
backend/
  pyproject.toml            # Python 3.11+；fastapi uvicorn sqlmodel aiosqlite openai pydantic pytest-asyncio
  data/                     # .gitignore：providers.json personas.json boards.json whoisspy.db
  app/
    main.py settings.py
    api/       matches.py  stream.py  catalog.py
    engine/    runner.py  steps.py  channel.py  events.py  faults.py
    games/
      base.py              # ★ GameDefinition / Step / ActionRequest 契约中枢
      registry.py
      werewolf/  definition.py  state.py  rules.py(纯函数)  prompts.py(rules 切片)
    agents/    agent.py  prompting.py  protocol.py   # 六层拼装、speech+monologue+action JSON 协议
    llm/       gateway.py  usage.py                 # 多端点、重试、token/费用计量
    storage/   models.py  repo.py                   # Repository Protocol + SQLite 实现
    config/    loader.py                            # pydantic 校验 JSON 配置；key 仅环境变量解析
  scripts/     run_match.py(--mock)  e2e_real.py
  tests/       conftest.py(MockLLM+故障注入)  test_rules_*  test_channel  test_faults  test_visibility  test_full_match_mock
frontend/  src/
  router/    MatchListView(/)  CreateMatchView(/create)  MatchView(/matches/:id)
  api/       client.ts  sse.ts        # EventSource：Last-Event-ID 重连、seq gap 补拉
  stores/    match.ts  matchList.ts  catalog.ts
  model/     events.ts  project.ts   # 事件→ViewModel 投影（纯展示，规则全在后端）
  components/match/  MatchStage.vue(★观赛/复盘共用)  SeatBoard  SpeechFeed  NightChannelPanel
    MonologuePanel  PhaseIndicator  VoteBoard  ViewToggle  UsagePanel
docs/      # 本文档树（按功能域拆分，见 README.md）
```

各子系统的详细设计：[agents-and-llm.md](agents-and-llm.md) · [game-plugin.md](game-plugin.md) · [events-storage.md](events-storage.md) · [engine.md](engine.md) · [frontend.md](frontend.md) · [api.md](api.md)
