# 事件模型与存储

事件流是唯一事实源（支柱 1 Reducer、支柱 4 单局单写者）。对局结束后事件流即完整对局记录，复盘直接重放（D7）。

## 事件类型总表

| 类型 | 可见性 | 说明 |
|---|---|---|
| `match.created` / `match.started` | public | 对局创建/开跑 |
| `match.finished` / `match.stopped` | public | 分出胜负 / 手动终止 |
| `role.dealt` | seat | 发牌结果（仅本人） |
| `phase.started` / `phase.ended` | public | 阶段边界 |
| `channel.round.started` / `channel.round.ended` | god | 频道轮次边界 |
| `channel.message` | seat=频道成员 | 频道发言（狼队夜聊） |
| `night.kill_target` | god | 定刀过程（提案分布/决胜/空刀） |
| `night.guard_target` | god | 守卫守护目标（standard-12） |
| `night.seer_query` / `night.seer_result` | result 仅预言家 | 验人 |
| `night.witch_action` | god | 女巫用药（救/毒/不用，standard-12） |
| `night.resolved` | public | 夜里死讯/平安夜（不报过程与死因；payload 含死因供 god 复盘） |
| `skill_state.notice` | seat=本人 | 猎人/狼王每晚技能状态（能否开枪，standard-12） |
| `gun.shoot` | public | 猎人/狼王开枪带人 |
| `sheriff.registered` | public | 上警名单 |
| `sheriff.badge` | public | 当选/移交/撕毁警徽 |
| `player.speech` | public | 发言（含竞选宣言/归票；`phase` 区分） |
| `player.last_words` | public | 遗言（被投出者） |
| `player.monologue` | god | 内心独白（D6） |
| `vote.cast` / `vote.resolved` | public | 投票（含警长投票/2 票权重）/ 计票结果 |
| `player.fallback` | god | 容错兜底触发记录 |

可见性由游戏插件 `visibility()` 标注（[game-plugin.md](game-plugin.md)），**出站前统一过滤**（支柱 3）：同一过滤函数服务 REST 与 SSE；沉浸视角响应体中不得出现任何 god/seat 数据（有测试锁死）。

## 存储表（SQLModel + SQLite）

- **match**：id、game_type、board_json、rng_seed、status、result、current_seq、created_at。
- **match_seat**：match_id、seat、role 回填 + **接入快照**（persona_id / style / strategy 快照、base_url、api_key_env、model、单价）——创建时展开固化（D10/D11），历史可复现。**不含 key 本体**。
- **game_event**：match_id + seq（对局内唯一递增）、type、day_index、phase、payload_json、vis_level、vis_seats_json。**append-only**，只有 MatchRunner 写入（支柱 4）。
- **llm_call**：token 数（prompt / completion / **cached_prompt_tokens** 前缀缓存命中）、cost_micros、latency、purpose、status，经 ref_event_id 弱关联事件；**不进事件流**，仅供用量面板与排障。旧库缺列由 `SqliteUsageRepository.init` 幂等补列。

Repository 抽象（storage/repo.py）：`MatchRepository` / `UsageRepository` Protocol + SQLite 实现，未来换 Postgres 不动上层（D9）。

## Reducer 约定

- `GameState` 只能由 `apply(state, event)` 逐条归约产生；随机结果（种子/分布/决胜）写入事件 payload。
- 验证策略：`apply` 重放事件流 ≡ 直接构造状态（单测）。

## SSE 契约

- `GET /api/matches/{id}/stream?view=immersive|god`：每条帧 `id: <seq>`、`event: game_event`、`data: <payload>`。
- 断线重连带 `Last-Event-ID`：服务端先补发（events?after_seq=）后切实时订阅。
- 前端按 seq 去重、检测 gap 自动补拉（[frontend.md](frontend.md)）。
