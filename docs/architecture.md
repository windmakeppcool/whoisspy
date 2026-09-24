# 架构总览

## 定位

基于网页的「多 AI 合作对抗观赏台」：多个 LLM 驱动的 AI 玩家打隐藏身份对抗游戏（狼人杀首发），人只观看——实时追更（SSE）与历史复盘共用同一套渲染。核心卖点是**多模型混战**（每座位独立端点+模型+人设/策略）、**狼队夜间私密频道商量战术**、**结构化内心独白**（言行不一可见）。

技术栈：前端 Vue 3 + TypeScript（Vite、Pinia），后端 FastAPI（Python 3.11+），SQLModel + SQLite（aiosqlite），openai SDK（OpenAI 兼容接入），SSE 推送。

## 四条设计支柱

1. **Reducer 架构**：GameState 由 append-only 事件流逐条 `apply` 归约；随机数走带种子的 `Random` 且结果（含分布/决胜）写入事件 → 未来时间轴/分叉重跑不堵死。
2. **Step 原语组合**：engine 通过 `StepContext` 暴露 IO 原语（emit / ask / ask_many / speech / collect_ballot），
   游戏插件在 `play(ctx, step)` 里编排自己的流程与结算（见 [game-plugin.md](game-plugin.md)）；
   抽象仅覆盖「阵营制 + 隐藏身份 + 轮流发言 + 投票」这一族，不做万能引擎。
3. **可见性是事件元数据**（public / seat / god），服务端出站前统一过滤（`core.filtered_view`），前端永远拿不到当前视角外的数据。
4. **单局单写者**：MatchRunner 独占事件 append（seq 由 DB 原子自增），SSE 以 seq 为游标断线补发。

## 分层与依赖方向

```
前端 Vue3+TS（Pinia + SSE 消费）
  对局列表 / 创建表单 / MatchView（观赛追更与历史详情共用 MatchStage 渲染）
        │ SSE 增量追新 + REST 回填
FastAPI：api/app.py（matches / events / stream / stop / usage / export / catalog）
engine/ 对局运行核心（与游戏无关）
  MatchRunner（单局 = 单 asyncio task；步进循环 / 容错链 / 记忆投影 / 终止语义）
  context.py（StepContext：插件唯一的 IO 面） ｜ faults.py 通用兜底
games/ 插件层
  base.py（GameDefinition + StepContext 契约）  registry.py（单板注册表）
  werewolf/  definition.py（状态机/校验/可见性/记忆行）  flow.py（步内流程）  rules.py（纯函数）  prompts.py（规则切片）
agents/（prompt 六层拼装 + JSON 协议 + 发言围栏）   llm/（OpenAI 兼容网关 + 重试 + token/费用计量）
storage/ Repository 抽象（SQLite 实现，append-only 事件表）
config/（JSON 加载校验；key 只走环境变量；接入白名单）
```

依赖规则（保持插件边界的关键）：

- `engine/` **不得出现任何具体游戏痕迹**（角色名/事件名/私有状态键），由 `tests/test_architecture.py` 锁死；
  游戏规则只能出现在 `games/<name>/`。
- `games/` 不 import `engine/` 内部实现，只依赖 `games/base.py` 的契约类型与引擎注入的 `StepContext`。
- `agents/` 不 import 具体游戏——prompt 拼装只消费插件暴露的规则切片与记忆行接口。
- `storage/` 无业务语义，只做持久化与出站可见性过滤；`api/` 不写事件，事件一律经 MatchRunner（单局单写者）。

## 目录结构（关键文件）

```
backend/
  pyproject.toml            # Python 3.11+；fastapi uvicorn sqlmodel sqlalchemy aiosqlite openai pydantic pytest-asyncio
  data/                     # .gitignore：providers.json personas.json boards.json whoisspy.db
  app/
    main.py                 # uvicorn 入口 / --tui 观看器
    api/       app.py       # FastAPI 应用工厂：校验、鉴权、CORS、runner 生命周期
    engine/    runner.py  context.py  faults.py
    games/
      base.py               # ★ GameDefinition / StepContext / Step 契约中枢
      registry.py           # 单板注册表（p9-standard）
      werewolf/  definition.py  flow.py  rules.py(纯函数)  prompts.py(rules 切片)
    agents/    protocol.py  # 六层拼装、speech+monologue+action JSON 协议、围栏防注入
    llm/       gateway.py   # 多端点、重试（含 openai 异常）、token/费用计量
    storage/   models.py  repo.py   # Repository Protocol + SQLite 实现 + 出站过滤
    config/    loader.py  defaults.py   # pydantic 校验 JSON 配置；key 仅环境变量解析
    tui/                     # 终端观看器（REST/SSE 客户端）
    export/    dialog.py     # 整局对话 JSON 导出
  scripts/     run_match.py(--mock)  e2e_real.py  export_dialog.py
  tests/       test_rules_werewolf  test_actions_werewolf  test_voting_flows  test_full_match_mock
               test_api_validation  test_seat_snapshot  test_cost  test_architecture …
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
