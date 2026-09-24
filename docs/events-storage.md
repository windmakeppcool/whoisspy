# 事件模型与存储

事件流是唯一事实源（支柱 1 Reducer、支柱 4 单局单写者）。对局结束后事件流即完整对局记录，复盘直接重放（D7）。

## 事件类型总表

| 类型 | 可见性 | 说明 |
|---|---|---|
| `match.created` | public | 对局创建（含 board_id / 板子 / 种子，创建后由 runner 首条幂等落库） |
| `match.started` | public | 开跑（payload 带可复现的 `rng_seed`） |
| `match.finished` / `match.stopped` | public | 分出胜负 / 被终止（`match.stopped.payload.reason`） |
| `role.dealt` | seat=本人 | 发牌结果 |
| `phase.started` | public | 阶段边界（`payload.phase` = 插件步骤 kind，`payload.day` 由插件 `phase_day` 给出） |
| `night.started` | public | 入夜（清空本夜动作收集，事件驱动归约） |
| `channel.round.started` / `channel.round.ended` | god | 频道轮次边界与提案分布 |
| `channel.message` | seat=频道成员 | 频道发言（狼队夜聊） |
| `night.kill_target` | god | 定刀过程（提案分布/决胜/空刀） |
| `night.seer_query` | god | 验人发起 |
| `night.seer_result` | seat=预言家 | 验人结果 |
| `night.witch_action` | god | 女巫用药（救/毒/不用） |
| `night.resolved` | public | 夜里死讯/平安夜：`deaths` 只带座位（值为空串），**不含死因** |
| `night.death_cause` | god | 死因（knife/poison），供上帝视角复盘 |
| `skill_state.notice` | seat=本人 | 猎人当夜技能状态（`can_shoot` 由死因决定） |
| `gun.shoot` | public | 猎人开枪带人（含放弃开枪） |
| `sheriff.registered` | public | 上警名单 |
| `sheriff.badge` | public | 当选/移交/撕毁警徽 |
| `day.speech_order` | public | 当天发言顺序（顺序来源与完整顺序，可复盘） |
| `player.speech` | public | 发言（含竞选宣言/PK 发言） |
| `player.last_words` | public | 遗言（被放逐者） |
| `player.monologue` | god | 内心独白（D6：每次调用都有） |
| `vote.cast` | public | 单张票（含弃票） |
| `vote.resolved` | public | 计票结果；**`scope` 区分放逐（exile）与警长选举（sheriff）**，只有 `exile` 会判死 |
| `player.fallback` | god | 容错兜底触发记录（LLM 调用失败/坏 JSON 修复失败） |
| `plugin.error` | god | 游戏插件的校验/兜底代码抛异常（与 LLM 调用失败区分记账） |

可见性由游戏插件 `visibility()` 标注（[game-plugin.md](game-plugin.md)），
**出站统一过滤**（支柱 3）：`core.filtered_view` 是唯一过滤点，REST/SSE/导出都走它；
沉浸视角响应体中不得出现任何 god/seat 数据（有测试锁死）。

## 存储表（SQLModel + SQLite）

- **match**：id、game_type、ruleset、board_json、rng_seed、status、result、current_seq、created_at。
- **match_seat**：match_id、seat、role 回填 + **创建时固化的接入与人设快照**
  （persona_id / style / strategy / provider_id / base_url / api_key_env / model / 三个单价字段）
  ——历史对局不依赖后续配置变更即可复现（D10/D11/D25）。**不含 key 本体**。
- **game_event**：match_id + seq（对局内唯一递增，`UNIQUE(match_id, seq)`）、type、day_index、phase、
  payload_json、vis_level、vis_seats_json。**append-only**，只有 MatchRunner 写入（支柱 4）；
  seq 由 DB 原子自增分配（`UPDATE match SET current_seq = current_seq + 1 … RETURNING`）。
- **llm_call**：token 数（prompt / completion / cached_prompt_tokens）、**cost_micros（按单价折算的真实费用）**、
  latency、purpose、status、ref_event_seq；**不进事件流**，仅供用量面板与排障。

Repository 抽象（storage/repo.py）：`MatchRepository` / `UsageRepository` Protocol + SQLite 实现，
未来换 Postgres 不动上层（D9）。旧库缺列/缺索引由 `init()` 里的幂等 DDL 补齐。

## Reducer 约定

- `GameState` 只能由 `apply(state, event)` 逐条归约产生；随机结果（种子/分布/决胜）写入事件 payload。
- 插件私有状态放 `state.extra`，同样只由 `apply` 修改。
- 验证策略：`apply` 重放事件流 ≡ 直接构造状态（单测）。

## SSE / 事件回放契约

- `GET /api/matches/{id}/events?after_seq=&view=`：REST 回放；`after_seq` 省略时读 `Last-Event-ID` 头。
- `GET /api/matches/{id}/stream?view=immersive|god`：每条帧 `id: <seq>`、`event: game_event`、`data: <payload>`；
  断线重连游标取 `last_event_id` 查询参数，缺省时读 `Last-Event-ID` 头（浏览器 EventSource 自动携带）。
- 前端按 seq 去重、检测 gap 自动补拉（[frontend.md](frontend.md)）；对局结束时服务端补拉尾帧再发
  `event: match_finished`。
