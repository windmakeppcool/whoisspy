# 对局引擎

`engine/` 与游戏无关：只负责跑完一局（步进、并发、容错、落事件），游戏规则全部来自 `GameDefinition` 插件。
解耦方式见 [decisions.md](decisions.md) D24 与 [game-plugin.md](game-plugin.md)。

## MatchRunner（单局单写者，支柱 4）

- 一局 = 一个 asyncio task（由 API 的 runner 注册表持有，关停时统一中断）；MatchRunner 独占事件 append。
- 生命周期：`match.created → match.started →（若干步）→ match.finished | match.stopped`。
- 步进循环：

```
emit match.created / match.started
deal → role.dealt（逐座位，仅本人可见）
while True:
    if 手动终止 / 步数超限: break（落 match.stopped）
    result = game.check_winner(state)          # 每步之前检查（等价于每步之后检查）
    if result: break
    step = game.next_step(state)
    if step.kind in ("", "noop"):
        result = game.check_winner(state)      # 插件可能在 next_step 里直接判了胜负
        if result is None: break（状态机停摆）
    emit phase.started（phase=step.kind, day=plugin.phase_day(state, step)）
    await plugin.play(ctx, step)               # 步内流程全部在插件里
```

- **终止语义**：`match.finished` 只在真正分出胜负时发出，状态写 `finished`；
  手动终止（`POST /{id}/stop`）、步数超限（>500 步）、状态机停摆一律落 `match.stopped`
  （payload 带 reason）并把 `match.status` 写成 `stopped`、`result.winner=null`。
- 事件写入顺序固定：插件标注可见性 → append（seq 单调）→ `apply` 归约。

## 步内执行（StepContext）

engine 不认识任何游戏步骤：`play(ctx, step)` 由插件实现，engine 只通过 `StepContext` 提供 IO 原语
（emit / ask / ask_many / speech / collect_ballot / monologue，见 [game-plugin.md](game-plugin.md)）。

- **串行/并行由插件决定**：狼队夜聊与白天发言串行（观赛节奏），收刀/投票/报名并行（防跟票）。
- 并发边界：同一局内只有插件声明的并行部分并发；事件写入由 runner 串行化（seq 由 DB 原子自增分配）。

## 容错链（engine/faults.py + llm/gateway.py）

任何 agent 调用沿固定链条降级，**绝不卡死整局**：

1. 单次调用超时 60s；网络/超时/限流/5xx 重试 ≤2（退避 2s/5s）。
   **可重试异常必须显式包含 openai SDK 的 `APIConnectionError/APITimeoutError/RateLimitError/InternalServerError`**
   ——它们不继承内置 `ConnectionError/TimeoutError`，只捕内置异常等于不重试（历史 bug S4）。
4xx 参数错/鉴权失败不重试。
2. 坏 JSON → 一次格式修复调用（修复提示里的 schema 顺序与本契约一致）。
3. 仍失败 → 兜底：**由插件按步骤给中性动作**（`neutral_action`）——投票=弃权、定刀=空刀、
   验人=不验、用药=不用药、发言=沉默；补发 `player.fallback`（god）。
   兜底绝不替玩家做决定（女巫步的兜底是 `pass`，不会用掉解药）。
   插件的 `validate_action`/`neutral_action` 自身抛异常时**不算 LLM 故障**：
   单独立 `plugin.error`（god）并回落通用中性动作（D28）。
4. 步级 5min 总时限：超时落 `player.fallback(step_timeout)` 并跳过该步剩余动作。

全部尝试记入 `llm_call`（含失败与费用），用量与排障不丢账。

## prompt 与记忆层

- 六层拼装（规则 → 身份 → style → strategy → 记忆 → 本步规则 + 指令）见 [agents-and-llm.md](agents-and-llm.md)。
- **记忆行的渲染规则属于插件**（`memory_line`）：engine 只负责按 `VisMeta` 过滤出该座位可见的事件。
- 阶段天数也由插件提供（`phase_day`），使 `phase.started` 的 `day_index` 与实际归属一致。

## 用量计量

每次调用都记 `llm_call`：prompt/completion/缓存命中 token、**按 units 单价折算的 `cost_micros`**
（单价来自 providers.json 的 `price_per_mtok_in/out/cached_in`，随座位快照固化）、延迟、状态、purpose。
汇总端点 `GET /api/matches/{id}/usage` 返回总量与分模型明细（含 `cache_hit_rate`）。

## 并发与存储约定

- 单局单写者：一局只有一个 runner 写事件；`game_event(match_id, seq)` 有唯一约束。
- seq 由 DB 原子自增（`UPDATE … RETURNING`）分配，多进程/多实例共库也不会撞号；
  `match.current_seq` 与库中最大 seq 保持一致。
- 「单进程单写者」仍是默认部署形态；若要多进程，请确认同一对局只被一个进程接管。
