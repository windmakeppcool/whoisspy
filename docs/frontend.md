# 前端（Vue 3 + TypeScript）

观赛追更与历史复盘**共用同一渲染组件**（MatchStage）：两者都是「按 seq 消费事件流」，差别只在数据来源（SSE 增量 vs REST 回填）。规则全在后端，前端只做事件→ViewModel 投影。

## 路由

| 路由 | 页面 | 职责 |
|---|---|---|
| `/` | MatchListView | 对局列表（进行中/历史） |
| `/create` | CreateMatchView | 创建表单：板子 + 每座位 persona/接入配置（M2 先硬编码座位配置） |
| `/matches/:id` | MatchView | 观赛/复盘，内嵌 MatchStage |

## 组件（components/match/）

- `MatchStage.vue`：★观赛/复盘共用的总渲染（座次、日/夜阶段、事件流）。
- `SeatBoard` 座次表 ｜ `SpeechFeed` 发言流 ｜ `NightChannelPanel` 狼队频道（god）｜ `MonologuePanel` 内心独白（god）｜ `PhaseIndicator` 阶段指示 ｜ `VoteBoard` 投票结果 ｜ `ViewToggle` 沉浸/上帝切换 ｜ `UsagePanel` 用量。

## 状态与投影

- Pinia：`match`（当前局事件缓冲与投影）、`matchList`、`catalog`（boards/personas/providers 预设）。
- `model/events.ts`：事件类型定义（与 [events-storage.md](events-storage.md) 对齐）。
- `model/project.ts`：事件→ViewModel **纯函数投影**（可单测），不做任何规则判断。

## SSE 消费（api/sse.ts）

- EventSource 带 `Last-Event-ID` 断线重连；服务端先补发后实时。
- 前端按 `seq` 去重；检测 seq 空洞自动 REST 补拉 `GET /events?after_seq=`。
- 按序应用投影，保证与历史详情逐事件一致。

## 视角切换（D8）

- 默认沉浸（immersive）；`ViewToggle` 一键切上帝（god）。
- **过滤在服务端**：前端切视角只是换 `?view=` 重新拉流，网络响应体中不得出现视角外数据；上帝视角下 NightChannelPanel / MonologuePanel 亮起。
