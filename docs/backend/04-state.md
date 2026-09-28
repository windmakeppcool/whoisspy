# 04 状态与 Reducer（state.py）

## 一、GameState（类型化字段，P6）

旧系统的 `state.extra` 私有字典取消，全部字段具名：

```python
@dataclass
class GameState:
    roles: dict[int, str]            # seat -> role
    alive: dict[int, bool]
    day: int = 0                     # 入夜时 +1；day=N 覆盖第 N 夜与第 N 天白天
    phase: str = ""                  # 最近一次 phase.started 的 kind
    sheriff: int | None = None       # 警长座位（destroy 后回 None）
    elect_done: bool = False         # 警长选举流程已走过（无论徽章归属）
    used_save: bool = False          # 女巫解药
    used_poison: bool = False        # 女巫毒药
    night: dict[str, Any] = field(default_factory=dict)   # 本夜收集：kill/saved/poison
    seer_results: dict[int, str] = field(default_factory=dict)  # target -> verdict
    speech_order: list[int] = field(default_factory=list)       # 当天发言顺序
    last_exile: int | None = None
    last_exile_tied: list[int] = field(default_factory=list)
    last_exile_was_alive: bool = False   # 放逐守门标记（D28.6 语义沿用）
    winner: GameResult | None = None
```

配套方法：

- `snapshot() -> dict`：全字段可读快照（trace 每阶段末尾落一条，debug 用）；
- `apply(event) -> None`：**唯一的状态修改入口**（下表）。

## 二、apply：事件 → 状态（reducer 规则）

| 事件 | 归约 |
|---|---|
| `phase.started` | `phase = payload.phase`；若 `phase == night_start` 则 `day += 1` |
| `night.started` | `night = {}`（清空本夜收集） |
| `night.kill_target` | `night["kill"] = target`（null/0 = 空刀，存 None） |
| `night.seer_result` | `seer_results[target] = verdict` |
| `night.witch_action` | `save → used_save=True, night["saved"]=True`；`poison → used_poison=True, night["poison"]=target` |
| `night.resolved` | `deaths` 的每个座位判死（`alive[seat]=False`；**只接受 roles 里真实存在的座位**） |
| `vote.resolved`（`scope=exile`） | 先记 `last_exile / last_exile_tied / last_exile_was_alive`（判死**前**的存活态），再判死 `exiled` |
| `gun.shoot` | `target` 判死（真实座位防御同上） |
| `sheriff.registered` | `elect_done = True` |
| `sheriff.badge` | `transfer → sheriff = to`；`destroy → sheriff = None` |
| `day.speech_order` | `speech_order = order` |
| 其余 | 不改状态（`role.dealt`/`match.*`/`channel.*`/`player.*`/`vote.cast`/god 级诊断事件） |

守门语义（沿用 D28.6）：`last_exile_was_alive` 在判死**之前**取样——只有「本轮真的从存活变死亡」
的座位才在 exile_resolve 里触发遗言/开枪链；对本就已死/幻觉座位，reducer 不写 alive 表，
流程守门也不放行。

## 三、不变量

1. **折叠一致性**：`fold(events) ≡ 现场状态`——从库读任意前缀事件逐条 apply，
   得到的 GameState 与现场逐字段相等（单测锁死；这是「事件即记录」的验收口径）。
2. `apply` 之外的代码**不得**修改 GameState 任何字段（flow 只读 state，写一律走 emit→apply）。
3. 判死防御：`_mark_dead` 只接受 `roles` 中真实存在的座位；`None`/幻觉座位静默忽略。
