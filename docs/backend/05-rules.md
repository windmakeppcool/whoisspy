# 05 纯函数规则（rules.py）

全部为无 IO 纯函数，单测直接覆盖全分支。游戏规则书（[games/werewolf.md](../games/werewolf.md)）
的语义口径在此处固化为可执行规格。

## 一、板子常量

```python
RULESET = "standard-9"
ROLES = {"wolf": 3, "seer": 1, "witch": 1, "hunter": 1, "villager": 3}
WOLF_ROLES = {"wolf"}
GOD_ROLES = {"seer", "witch", "hunter"}
GUN_ROLES = {"hunter"}
DEATH_KNIFE, DEATH_POISON = "knife", "poison"
WOLF_MEETING_ROUNDS = 2      # CLI --wolf-rounds 可覆盖
MAX_DAYS = 8                 # CLI --max-days 可覆盖
```

boards.json 退出（D32）：板子即代码常量；没有多板校验，`roles` 也不可能配错。

## 二、发牌 deal(seed)

把 9 个角色展开成列表 → `Random(seed).shuffle` → 座位 1–9 依次领角色。
同 seed 必得同分配（单测锁死）。

## 三、定刀 decide_kill(proposals, rng, valid_targets)

`proposals: {seat: target}`（target=0 表示弃权）：

1. 有效票 = target ∈ valid_targets 的提案；
2. 有效票为空 → **空刀**（`decided_by="empty"`，target=None）；
3. 计多数：唯一最高 → 刀该目标（`majority`）；
4. 并列最高 → `rng.choice(并列者对应目标)`（`rng`，随机源与决胜目标写入事件 payload 供复盘）。

## 四、计票 tally_votes(votes, sheriff=None)

`votes: {voter: target}`（0=弃权）：

- 每个非零 target 计 1 票；**警长的非零票计 2 票**（sheriff ∈ votes 时）；
- 唯一最高 → `{exiled: 最高者, tie: False, tied: []}`；
- 并列最高 → `{exiled: None, tie: True, tied: [并列者]}`。

## 五、夜结算 resolve_night(night) → deaths

`night = {kill: K|None, saved: bool, poison: P|None}`，结算矩阵（规则书二）：

| 情形 | 结果 | 死因 |
|---|---|---|
| P 被毒（任意组合，含 K=P） | 死亡 | poison（**解药不挡毒**；不能开枪） |
| K 被救（saved 且 K≠P 且 K≠None） | 免死 | — |
| K 未被救（K≠None 且 K≠P） | 死亡 | knife（可开枪） |
| K=P 未救 | 死亡 | knife（毒优先级低于刀；可开枪） |
| K=P 已救 | 死亡 | poison（刀被化解仍死于毒；不能开枪） |
| 空刀（K=None 且无 P） | 平安夜 | — |

返回 `{seat: cause}`（同时至多 2 死：刀口 + 毒口，或同刀同毒合一）。

## 六、胜负 check_winner(state, *, day_cycle_done)

检查时机只有两处（02-flow 主循环）：夜结算后、放逐结算后。`day_cycle_done` 仅在后者为 True。

**好人胜**：存活狼数 == 0（`reason="狼人全部出局"`）。

**狼胜**（任一）：

1. 神职（seer/witch/hunter）存活 == 0（屠边）；
2. 平民存活 == 0（屠边）；
3. 存活狼数 ≥ 存活好人数（屠城）；
4. `day >= MAX_DAYS` 且当天白天流程已走完（`day_cycle_done`）仍存活狼 > 0（时限）。

> 时限口径（M4 回归语义沿用）：`day` 在入夜自增，`day=N` 覆盖第 N 夜与第 N 天；
> 时限是「第 max_days 天放逐结算结束后」才判，不会出现白天没打就判狼胜。
> 夜结算后的检查点不判时限（`day_cycle_done=False`）。

## 七、动作校验 validate_action(state, phase, ask_spec, action) → action

`ask_spec` 携带本次调用的 `action_type` 与 `candidates`（[07-agent.md](07-agent.md)）。
校验失败的动作**整体降级为该 phase 的中性动作**（不是报错——LLM 输出不可信是常态）：

1. `action.type` 必须 ∈ 该 phase 允许集合（wolf_meeting/closing: kill；seer_check: check；
   witch_turn: save/poison/pass；speech_order: speech_order；ballot/day_vote: vote；
   sheriff_register: register；last_words/serial_speech/day_speech: speech；gun: shoot；badge: badge）；
2. `target` 必须 ∈（candidates ∩ 存活），否则按**弃权（target=0）**处理
   （speech 类 target 无意义，恒 0）；
3. 女巫特例：`used_save` 或 `night.kill` 为空 → `save` 降级 `pass`（解药不消耗）；
   `used_poison` → `poison` 降级 `pass`；
4. `register` 只取 `yes: bool`；其余非法字段忽略。

## 八、中性动作 neutral_action(phase)

每 phase 的「没答上来」动作（D25/S3 语义：兜底绝不替玩家做决定）：

| phase | 中性动作 |
|---|---|
| wolf_meeting / closing | `{type: kill, target: 0}`（弃权） |
| seer_check | `{type: check, target: 0}`（不查验） |
| witch_turn | `{type: pass, target: 0}`（**不用药**——绝不能默认用解药） |
| speech_order | `{type: speech_order, target: 0}`（交给 rng 起始） |
| ballot / day_vote | `{type: vote, target: 0}`（弃票） |
| sheriff_register | `{type: register, yes: False}`（不上警） |
| speech 类 / last_words | `{type: speech, target: 0}`（空发言） |
| gun | `{type: shoot, target: 0}`（放弃开枪） |
| badge | `{type: badge, target: 0}`（撕毁警徽） |
