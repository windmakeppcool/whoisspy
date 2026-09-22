# 狼人杀（首发游戏）

规则分期见 [decisions.md](../decisions.md) D2：v1 为**最小流程局**，标准完整局（预女猎白/警长等）后续做可自选档位。板子只配角色组合，技能写死（D3）。

## v1 最小流程局

- 角色：狼人、预言家、平民。6-10 人。
- 胜负：**好人胜 = 狼全灭；狼胜 = 存活狼 ≥ 存活好人**。
- 流程状态机（`next_step`）：

```
NIGHT_WOLF（狼队频道商量 + 定刀）
  → NIGHT_SEER（预言家验人）
  → DAWN（结算夜死，公布死讯）
  → DAY_SPEECH（存活玩家按序发言）
  → DAY_VOTE（并行投票放逐）
  → 胜负检查 → 未分胜负回到 NIGHT_WOLF
```

- 夜里狼刀死 + 白天放逐死都即时做胜负检查（1 狼 1 民 = 狼胜等边界有单测锁死）。

## 发牌校验（validate_board）

- `6 ≤ n ≤ 10`；狼 `1 ~ ⌈n/3⌉`；预言家 `0 ~ 2`；民 `≥ 1`。越界直接拒绝创建。
- `deal` 用对局带种子 `rng` 洗牌发牌，分配结果经 `role.dealt` 事件落流（seat 可见）。

## 狼队夜间私密频道（D4，核心差异化）

- `ChannelMeeting(channel_id="wolf", members=存活狼, topic="定刀", rounds, closing_action=并行提案定刀)`。
- 轮内**串行**发言（每狼看到前狼发言再说话）；收刀**并行** gather 各狼目标提案，多数决定刀，平票用对局 rng 决出。
- 防死循环：`rounds` 固定（默认 2，boards 配置 0~3 可调）；每狼总调用次数 ≤ rounds+1；某狼调用失败不补轮；步级 5min 总时限兜底（[engine.md](engine.md)）。
- 定刀事件 `night.kill_target` 的 payload 含种子/分布/决胜信息（god 可见）；刀人结果并入 `night.resolved`（public，只报死讯不报过程）。

## 规则切片（rule_slices，供 D12 注入）

| 切片键 | 内容 | 注入时机 |
|---|---|---|
| `overview` | 阵营、胜利条件、流程一览 | 每次调用 |
| `night_wolf` | 狼队频道礼仪、定刀方式、悍跳/倒钩话术空间 | NIGHT_WOLF 相关步骤 |
| `night_seer` | 验人语义（查验阵营）与结果保密义务 | NIGHT_SEER |
| `day_speech` | 发言秩序、禁止场外、发言长度要求 | DAY_SPEECH |
| `day_vote` | 投票资格、平票规则、放逐结算 | DAY_VOTE |

## 板子（boards.json）

| id | 角色组合 | 备注 |
|---|---|---|
| `p6-classic` | 2 狼 + 1 预 + 3 民 | 默认最小局 |
| `p8-classic` | 2 狼 + 1 预 + 5 民 | |
| `p10-no-seer` | 3 狼 + 7 民 | 无预言家压力测试 |
| `custom` | 请求体给 roles，服务端 validate_board 校验 | |

每板含 `wolf_meeting_rounds` 字段；后续标准局在此加 `ruleset` 档位字段扩展（D2）。
