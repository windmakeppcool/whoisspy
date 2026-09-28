# 03 事件目录（events.py）

事件流是唯一事实源（P2）。每条事件落库后**立即**经 `state.apply` 归约（[04-state.md](04-state.md)）。
可见性在 `flow.py` emit 时**显式传参**（默认 public），随事件落库；出站（导出/终端）只按库里的
可见性过滤，客户端不做二次解释（P5）。

```python
@dataclass
class Event:
    seq: int                 # 对局内单调递增，从 1 开始
    type: str
    day_index: int           # 事件归属天（入夜时 +1，见 04-state.md）
    phase: str               # 事件发生时的阶段 kind
    payload: dict
    vis: Vis                 # Vis(level="public"|"seat"|"god", seats=[...])

public() / god() / seat(n)   # events.py 提供的三个可见性构造器
```

## 一、事件总表

| 类型 | 可见性 | payload | 触发时机（02-flow 章节） |
|---|---|---|---|
| `match.created` | public | `{seed, roles{角色:数量}, wolf_meeting_rounds, max_days, model_assignments[]}` | 开局一.1 |
| `match.started` | public | `{seed}` | 开局一.2 |
| `match.finished` | public | `{winner: wolf\|good, reason}` | 主循环胜负 |
| `match.stopped` | public | `{reason}` | 02-flow 六 |
| `role.dealt` | seat=本人 | `{seat, role}` | 开局一.3 |
| `phase.started` | public | `{phase, day, label}`（label=中文阶段名，见下表） | 每阶段入口 |
| `night.started` | public | `{day}` | 3.1（reducer 清空本夜收集） |
| `channel.round.started` | god | `{channel: "wolf", members[]}` | 3.2 |
| `channel.message` | seat=存活狼 | `{seat, text}` | 狼队夜聊发言 |
| `channel.round.ended` | god | `{channel, proposals{seat:target}}` | 3.2 收刀后 |
| `night.kill_target` | god | `{target: int\|null, decided_by, proposals}` | 3.2 末 |
| `night.seer_query` | god | `{seat, target}` | 3.3（target=0 也落） |
| `night.seer_result` | seat=预言家 | `{seat, target, verdict: wolf\|good}` | 3.3（target 存活才落） |
| `night.witch_action` | god | `{seat, act: save\|poison\|pass, target}` | 3.4 |
| `night.resolved` | public | `{day, deaths{seat: ""}}`——**只有座位，值恒为空串，不含死因** | 3.6 |
| `night.death_cause` | god | `{causes{seat: knife\|poison}}` | 3.6（有死亡才落） |
| `skill_state.notice` | seat=本人 | `{seat, can_shoot}` | 3.6（每个猎人） |
| `sheriff.registered` | public | `{seats[]}` | 3.5 |
| `sheriff.badge` | public | `{action: transfer\|destroy, to}` | 3.5 / 五 |
| `day.speech_order` | public | `{order[], start, decided_by: sheriff\|rng\|rng_fallback}` | 4.1 |
| `player.speech` | public | `{seat, text}`（超 240 字已截断） | 各发言 |
| `player.last_words` | public | `{seat, text}` | 4.4 遗言 |
| `player.monologue` | god | `{seat, text}` | **每次 ask 成功且有独白都落**（D6） |
| `vote.cast` | public | `{seat, target}`（0=弃权） | 各投票，座位升序落 |
| `vote.resolved` | public | `{votes{seat:target}, title, scope: exile\|sheriff, sheriff?, exiled?, tie, tied[]}` | 3.5 / 4.3 / 4.4 |
| `gun.shoot` | public | `{seat, target, text}`（target=0 放弃） | 五 |
| `player.fallback` | god | `{seat, reason, purpose}` | [07-agent.md](07-agent.md) 容错链 |
| `rule.error` | god | `{phase, reason}` | 校验/兜底代码自身抛异常（旧 `plugin.error` 改名） |

变更说明（相对旧系统）：

1. **`phase.started` 携带 `label`**：中文名由 flow 落事件时给出，投影层不再各自维护映射表
   （旧 TUI/前端/插件三处 `PHASE_LABELS` 漂移的根治，D31）。
2. **`plugin.error` → `rule.error`**：插件系统已删；语义不变（规则代码崩溃与 LLM 失败分开记账）。
3. `night.resolved.deaths` 的值恒为空串（死因只在 god 级 `night.death_cause`）——语义沿用。
4. `vote.resolved` 保留 `scope` 区分放逐/警长票；只有 `scope=exile` 会驱动 reducer 判死。

## 二、阶段 kind 与中文 label

| kind | label | 夜/昼 |
|---|---|---|
| `night_start` | 入夜 | 夜 |
| `wolf_meeting` | 狼队密谋 | 夜 |
| `seer_check` | 预言家查验 | 夜 |
| `witch_turn` | 女巫用药 | 夜 |
| `sheriff_elect` | 警长竞选 | 夜（第 1 天夜末） |
| `night_resolve` | 天亮结算 | 夜 |
| `speech_order` | 发言定序 | 昼 |
| `day_speech` | 白天发言 | 昼 |
| `day_vote` | 放逐投票 | 昼 |
| `exile_resolve` | 放逐结算 | 昼 |

导出分段与「第 N 夜/第 N 天」的归属由上表「夜/昼」列决定（[11-export.md](11-export.md)）。
**警长竞选归入当夜**（D20/D21：夜末、死讯公布前）——旧实现三处客户端判定不一致，此处统一。

## 三、不变量（测试锁死）

1. `seq` 从 1 起严格 +1，无空洞无重复（`UNIQUE(match_id, seq)` 兜底）；
2. 并行收集类事件的落库序 = 座位升序（P3）；
3. `deaths`/`causes`/`votes`/`proposals` 等字典的键为座位号（JSON 落库后变字符串，
   读取方一律 `int(k)` 归一）；
4. 除 `role.dealt`/`skill_state.notice`/`night.seer_result`/`channel.message` 为 seat 级、
   上表标注 god 者外，其余一律 public；**任何视角都拿不到「可见性之外」的数据**
   （导出过滤是唯一出站过滤点）。
