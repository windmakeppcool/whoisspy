# 对局引擎

engine/ 与游戏无关：只负责跑完一局（步进、并发、容错、落事件），游戏规则全部来自 GameDefinition 插件。

## MatchRunner（单局单写者，支柱 4）

- 一局 = 一个 asyncio task；MatchRunner 独占事件 append，seq 由它分配递增。
- 生命周期：`match.created → started →（若干步）→ finished | stopped`；`POST /{id}/stop` 置停止标志，当前步收尾后落 `match.stopped`。
- 步进循环：

```
while (winner := game.check_winner(state)) is None:
    step = game.next_step(state)
    events = await execute(step)          # 4 原语之一，步内可并行
    for ev in events:
        game.visibility(ev, state)        # 入库前标注可见性
        append(ev); game.apply(state, ev) # 单写者 + Reducer
```

## Step 原语执行语义

原语定义见 [game-plugin.md](game-plugin.md)。执行要点：

- **ChannelMeeting**：轮内串行（后一狼的 prompt 含前狼发言）；`closing_action` 并行 gather 提案后按多数决结算，平票走对局 rng。轮数固定、失败不补轮（详见 [games/werewolf.md](games/werewolf.md)）。
- **SerialSpeech**：严格按序，一个接一个（观赛「追更」节奏感来源）。
- **Ballot**：**并行**收集全部投票再统一开票，防跟票；`tie_policy` 带种子随机。
- **SoloAction**：单人私密调用，结果可见性按 `outcome_visibility_seats`。

## 容错链（engine/faults.py）

任何 agent 调用沿固定链条降级，**绝不卡死整局**：

1. 超时 60s/次 → 仅网络/5xx 重试 ≤2（退避 2s/5s）。
2. 坏 JSON → 一次格式修复调用。
3. 仍失败 → 兜底：发言=沉默、投票=弃权、定刀=**空刀（放弃刀人）**、验人=no_result、用药=不用药、守卫=不守；补发 `player.fallback`（god）。兜底一律取中性动作，绝不替玩家随机做主。
4. 步级 5min 总时限：超时同步兜底结算当前步。

全部尝试记入 llm_call（含失败），用量与排障不丢账。

## 并发边界

- 步内可并行的只有原语自身声明的并行部分（收刀 gather、Ballot 收票）；跨步严格串行。
- 同局内不共享可变状态给并行分支；提案收集后在 MatchRunner 内串行结算落事件。
