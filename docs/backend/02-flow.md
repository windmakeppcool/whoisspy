# 02 对局流程规格（flow.py）

一局 = 一个直排 async 调用链。本文是 `flow.py` 的行为规格——每个阶段的**问谁、按什么顺序问、
落哪些事件、怎么结算**。规则语义与 [games/werewolf.md](../games/werewolf.md)（规则书）一致，
本文补充实现口径；两者冲突时以本文为准并回改规则书。

通用约定：

- 「问」= `run.ask(seat, spec, purpose)`；「发言」= `run.speak(...)`（落 `player.speech` + 独白）；
  「收票」= `run.ballot(voters, candidates, ...)`（并行问、按座位序落 `vote.cast`）。
- 每次 `ask` 的返回都可能是**兜底动作**（LLM 失败/坏 JSON/非法动作），流程不感知差异——
  兜底语义见 [07-agent.md](07-agent.md)。
- 事件 payload 与可见性逐条见 [03-events.md](03-events.md)。

## 一、开局（一次性）

```
落 match.created {seed, roles 配比, wolf_meeting_rounds, max_days, model_assignments}
落 match.started {seed}
发牌：rules.deal(seed) → 落 role.dealt × 9（每条 seat=本人可见）→ 回填 match_seat.role
建 GameState（roles/alive 全 True）
打印模型分配清单（stdout）
```

## 二、主循环

```
while True:
    night_phase(run)                       # 第三节
    if w := rules.check_winner(state, 夜结算后): break
    day_phase(run)                         # 第四节
    if w := rules.check_winner(state, 放逐结算后=day_cycle_done): break
落 match.finished {winner, reason}；否则任何终止路径落 match.stopped {reason}
```

护栏（触发即 stopped，reason 写明）：单局 LLM 调用总数 > `max_calls`（默认 600）；
单个阶段抛出未捕获异常（先落 `rule.error` 再 stopped）；Ctrl+C（reason=手动终止）。
胜负判定口径见 [05-rules.md](05-rules.md) 第五节。

## 三、夜间

### 3.1 入夜（night_start）

```
day += 1；落 phase.started {phase: night_start, day, label: 入夜}
落 night.started {day}          # reducer 清空本夜动作收集
```

### 3.2 狼队密谋（wolf_meeting）

```
落 phase.started {wolf_meeting}
wolves = 存活狼（座位升序）
若 wolves 为空 → 落 night.kill_target {target: null, decided_by: no_wolf, proposals: {}}，结束
落 channel.round.started {channel: wolf, members: wolves}（god）
频道夜聊：for _ in range(wolf_meeting_rounds - 1): for wolf in wolves(升序): speak(狼, 夜聊指令)
    # 串行：后一狼的记忆层含前狼发言（channel.message，seat=狼队）
并行收刀：ask(每狼, 收刀指令, candidates=全体存活) → proposals {seat: target}
落 channel.round.ended {channel: wolf, proposals}（god）
target, decided_by = rules.decide_kill(proposals, rng, valid=存活)
落 night.kill_target {target, decided_by, proposals}（god）
```

- `decided_by`：`majority`（多数）/ `rng`（平票决胜）/ `empty`（全员弃权→空刀）/ `no_wolf`。
- 非法目标（死座/幻觉座/不在候选）在 `ask` 校验时已降级为弃权（target=0），见 [07-agent.md](07-agent.md)。

### 3.3 预言家查验（seer_check）

```
落 phase.started {seer_check}
seer = 存活的预言家座位（无则跳过本阶段）
action = ask(seer, 查验指令, candidates=全体存活, 0=不查验)
落 night.seer_query {seat, target}（god）
若 target 存活：落 night.seer_result {seat, target, verdict: wolf|good}（seat=预言家）
落独白
```

### 3.4 女巫用药（witch_turn）

```
落 phase.started {witch_turn}
witch = 存活女巫（无则跳过）
has_save / has_poison 由 state.used_save / used_poison 得出
指令的 prompt_extra 按状态渲染：
  - 解药在手且有刀口：「当晚刀口：K 号玩家（用解药可救活）。」
  - 解药在手且空刀：「今晚是空刀（无人被狼刀），解药无法使用。」
  - 解药已用：「解药已用完，你只知道毒药是否还在。」
action = ask(witch, 用药指令, candidates=全体存活)
act ∈ {save, poison, pass}（校验：空刀夜/已用解药 → save 降级 pass；已用毒药 → poison 降级 pass）
落 night.witch_action {seat, act, target}（god）；落独白
```

### 3.5 警长竞选（sheriff_elect，仅第 1 天，死讯公布前）

```
落 phase.started {sheriff_elect}
registered = [s for s in 存活 if ask(s, 上警指令).yes]   # 并行问、按座位序归并
落 sheriff.registered {seats: registered}
if registered 为空 或 == 全体存活: 落 sheriff.badge {action: destroy}，结束
if len(registered) == 1: 落 sheriff.badge {action: transfer, to: 唯一者}，结束
宣言：for seat in registered(升序): speak(上警宣言)
第一轮：voters=未上警者，ballot(voters, candidates=registered)
    tally = rules.tally_votes(votes)（无警长权重）
    落 vote.resolved {votes, title: 警长投票, scope: sheriff, exiled, tie, tied}
    若平票：平票者再宣言 → voters=其余全体（含已上警者），ballot(候选=平票者)
        落 vote.resolved {…, title: 警长 PK 投票, scope: sheriff}
        再平票 → 落 sheriff.badge {action: destroy}，结束
落 sheriff.badge {action: transfer, to: 当选者}
```

> `scope="sheriff"` 的 `vote.resolved` **不判死**（历史 bug X2 语义保留）。
> 「无人上警/全员上警 → 警徽丢失后，本局不再有警长」：后续天数的 sheriff_elect 不再执行
> （`state.elect_done` 只看是否已走过选举流程）。

### 3.6 天亮结算（night_resolve）

```
落 phase.started {night_resolve}
result = rules.resolve_night(state.night)     # 结算矩阵见 05-rules.md
落 night.resolved {day, deaths: {seat: ""}}   # 公开死讯，只有座位没有死因
若 deaths 非空：落 night.death_cause {causes: {seat: knife|poison}}（god）
对每个猎人座位（存活或本轮死亡都要通知）：
    落 skill_state.notice {seat, can_shoot: 死因 != poison}（seat=本人）
    # 本夜未死的猎人 can_shoot=True（无意义但保持通知一致）；被毒死者 False
若 deaths 非空：resolve_deaths(run, causes)   # 第五节死亡结算链
```

## 四、白天

### 4.1 发言定序（speech_order）

```
落 phase.started {speech_order}
alive = 存活（升序）
若警长存活：
    target = ask(警长, 定序指令, candidates=alive).target
    start = target ∈ alive ? target : rng.choice(alive)；decided_by = sheriff | rng_fallback
否则：start = rng.choice(alive)；decided_by = rng
order = 从 start 起按座位号升序环绕
落 day.speech_order {order, start, decided_by}
```

### 4.2 白天发言（day_speech）

```
落 phase.started {day_speech}
for seat in order（严格串行，跳过中途死亡者——正常流程不会发生，防御式）:
    speak(seat, 白天发言指令)        # 文本超 240 字在 emit 时截断
```

### 4.3 放逐投票（day_vote）

```
落 phase.started {day_vote}
votes = ballot(全体存活, candidates=全体存活, 0=弃权)
tally = rules.tally_votes(votes, sheriff=state.sheriff)   # 警长 1 人 2 票
落 vote.resolved {votes, title: 放逐投票, scope: exile, sheriff, exiled, tie, tied}
```

### 4.4 放逐结算（exile_resolve）

```
落 phase.started {exile_resolve}
若 vote.resolved 平票：
    平票者（仍存活者，升序）依次 speak(PK 发言)
    pk_votes = ballot(其余全体存活, candidates=平票者)
    pk_tally = rules.tally_votes(pk_votes, sheriff)      # 警长若非平票者仍 2 票
    落 vote.resolved {votes: pk_votes, title: 放逐 PK 投票, scope: exile, …}
    再平票 → 平安日：本次放逐无人出局，直接进入下一次 night（先过胜负检查）
exile = 最终 exiled（平安日为 None）
若 exile 存在（且 last_exile_was_alive 防重复守门，见 04-state.md）:
    遗言：ask(exile, 遗言指令) → 落 player.last_words {seat, text} + 独白
    resolve_deaths(run, {exile: "exile"})
```

## 五、死亡结算链 resolve_deaths(causes)

夜死与放逐共用。**只对本轮真实发生「存活→死亡」迁移的座位触发；被枪杀者不连锁。**

```
for seat in sorted(causes):
    # 防御：座位必须真实存在，且此刻确实已死（判死事件已先于此函数落库并归约）
    若 seat 不在 roles 或 state.alive.get(seat): continue
    # （正常流程下 causes 的 key 必然已由 reducer 判死；此守门是幻觉座位/判死未生效的兜底）
    若 roles[seat] == hunter 且 cause ∈ {knife, exile}:   # 被毒死不能开枪
        target = ask(seat, 开枪指令, candidates=存活).target
        落 gun.shoot {seat, target, text: 附带发言}        # target=0 → 放弃开枪
        落独白
        若 target 且 state.sheriff == target: badge_transfer(run, target)
        # 被枪杀的警长也必须处理徽章（临终移交或撕毁，向已死者问询如遗言）
        # 被枪杀者：无遗言、不再触发其开枪（哪怕他也是猎人）
    若 state.sheriff == seat: badge_transfer(run, seat)    # 死者本人是警长

badge_transfer(run, actor):
    target = ask(actor, 移徽指令, candidates=存活).target
    target 存活 → 落 sheriff.badge {action: transfer, to: target}
    否则      → 落 sheriff.badge {action: destroy}
    落独白
```

## 六、终止与收尾

| 路径 | 行为 |
|---|---|
| 分出胜负 | `match.finished {winner, reason}`；match.status=finished；result_json 落库 |
| Ctrl+C | 落 `match.stopped {reason: 手动终止}`；status=stopped |
| 调用数超限 | 同上，reason=`LLM 调用数超限（>600）` |
| 流程异常 | 先落 `rule.error {phase, reason}`（god），再 `match.stopped {reason: 流程异常…}` |
| 收尾 | 打印结果与用量汇总 → 导出 JSON → 关闭 DB |

任何路径都必须走到「关闭 DB」——用 `try/finally` 包住整个 `run_match`。

## 七、事件落库顺序（确定性，P3）

同一批并行询问（收刀/上警/各类投票）的**响应收集是并行的，事件落库是串行按座位升序**的：
先 `await gather(所有 ask)` 拿到全部动作，再 `for seat in sorted(...)` 逐个 `emit(vote.cast)` 与独白。
发言类（狼聊/宣言/白天发言/PK/遗言/移徽/开枪）保持**严格串行**（后发言者的记忆层含先发言者内容）。
