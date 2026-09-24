# 狼人杀（唯一板子：standard-9）

> **单板收敛（D23）**：本项目只支持 standard-9 这一套板子（9 人 = 3 狼 + 预言家 + 女巫 + 猎人 + 3 民）。
> 极简局、12 人局、守卫、狼王等配置已全部移除——配置面越小，出错面越小。
> 新增板子前请先读 [game-plugin.md](../game-plugin.md) 与 [decisions.md](../decisions.md)。

实现位置：

| 文件 | 职责 |
|---|---|
| `backend/app/games/werewolf/rules.py` | 纯函数：板子校验、发牌、计票、定刀、夜间结算、胜负 |
| `backend/app/games/werewolf/definition.py` | 状态机（`next_step`/`apply`）、动作 schema 与校验、可见性、记忆行、规则切片 |
| `backend/app/games/werewolf/flow.py` | 步内流程（谁行动、怎么结算、写哪些事件）——engine 只提供 `StepContext` 原语 |
| `backend/app/games/werewolf/prompts.py` | 规则切片文本（按步骤注入，D12） |

---

## 一、角色与配置

| 角色 | 阵营 | 数量 | 技能 |
|---|---|---|---|
| 狼人 | 狼人 | 3 | 每晚在私密频道商量后共同定刀（多数决，平票 rng，全员弃权=空刀） |
| 预言家 | 好人 | 1 | 每晚查验一人，得知「好人/狼人」（结果仅本人可见） |
| 女巫 | 好人 | 1 | 解药×1（救当晚刀口）、毒药×1（毒杀一人），**每晚最多用一瓶** |
| 猎人 | 好人 | 1 | 死亡时可开枪带走一人；**被毒死不能开枪** |
| 平民 | 好人 | 3 | 无技能，靠发言与投票 |

- 板子校验：`roles` 必须严格等于上述组合（多一个守卫/狼王、少一个平民都会被 422 拒绝）。
- 可调项：`wolf_meeting_rounds`（狼队夜聊的**总调用次数**，默认 2 → 每狼 1 次频道发言 + 1 次收刀提案；
  设 1 则只收刀）、`max_days`（天数上限，默认 8）。

## 二、夜间流程与结算

夜晚顺序：**狼队商量（ChannelMeeting）→ 预言家查验 → 女巫用药 → 猎人技能状态通知**。

```
NIGHT_START（清空本夜动作收集）
  → WOLF_MEETING（狼队频道串行夜聊 + 并行收刀，多数决定刀）
  → SEER_CHECK（预言家验人，0 = 不查验）
  → WITCH_TURN（女巫：save/poison/pass，空刀夜不可用解药）
  → SHERIFF_ELECT（仅第 1 天：警长竞选，见第三节）
  → NIGHT_RESOLVE（结算矩阵出死讯 → 技能状态通知 → 开枪 → 警徽移交）
  → SPEECH_ORDER → DAY_SPEECH → DAY_VOTE → EXILE_RESOLVE（见第四节）
  → 胜负检查 → 未分胜负进入下一夜
```

### 结算矩阵

设刀口 K、是否用解药 S、毒目标 P：

| 情形 | 结果 | 死因 |
|---|---|---|
| P 被毒（任意组合） | **死亡**（解药不挡毒） | poison（不能开枪） |
| K 被救（S 且 K≠P） | 免死 | — |
| K 未被救 | 死亡 | knife（可开枪） |
| K = P（同刀同毒） | 未救 → 死亡；已救 → 刀被化解仍死于毒 | 未救 knife（可开枪）／已救 poison |
| 空刀（K 为 0/None） | 无人死于刀 → 平安夜 | — |

- 毒优先级：`狼杀 > 女巫毒`——同刀同毒且未救时认定刀杀（可开枪）。
- **空刀之夜无人死于刀**，女巫也无法对空刀口用药（`validate_action` 会把 save 降级为 pass，解药不被消耗）。
- 死因不对外公布：公开事件 `night.resolved` 只带死亡座位，死因另落 god 级 `night.death_cause`（复盘用）。

### 女巫的刀口信息

解药尚在时，女巫行动请求会带上当晚刀口（`ActionRequest.prompt_extra` 渲染进指令层）；
解药用尽则不再告知；空刀夜明确告知「解药无法使用」。

### 技能状态通知

夜序末尾向猎人发 `skill_state.notice`（仅本人可见）：`can_shoot` 由当晚死因决定
（被毒死为 false）。

## 三、警长竞选（仅第 1 天，夜末、死讯公布前，D21）

1. 全体并行选择是否上警。
2. 恰 1 人上警：自动当选；无人上警或全员上警：**警徽丢失**。
3. 警上发言：上警玩家依次发表竞选宣言。
4. 警长投票：**未上警玩家**投票（并行收集）；得票最多者当选。
5. 平票 → PK：平票者再次发言，**其余所有玩家（含已上警者）**再投；再平票 → 警徽丢失。

> 选举票用 `vote.resolved` 且 `scope="sheriff"` 标记：**它不是放逐**，归约时不会把当选者判死（历史 bug X2）。

## 四、白天流程

### i. 发言定序（`SPEECH_ORDER`）

- 有警长：由警长指定今天的第一位发言人（`action.type="speech_order"`）。
- 无警长：rng 随机起始。
- 顺序一律按座位号升序环绕，并落公开事件 `day.speech_order`（含完整顺序，可复盘）。

### ii. 发言（`DAY_SPEECH`）

严格按定序串行，每人上限 240 字（观赛「追更」节奏感来源）。

### iii. 投票放逐（`DAY_VOTE`）

- 全体存活玩家并行投票，**警长 1 人 2 票权重**；0 表示弃权。
- 得票最多且唯一 → 出局；并列最高 → **PK**：平票者再发言，其余玩家全体重投。
- PK 再平票 → **平安日**，无人出局。

### iv. 放逐结算（`EXILE_RESOLVE`）

1. 被投出者发表遗言（`player.last_words`）。
2. 被投出的猎人（非毒死）可开枪（`gun.shoot`），被枪杀者无遗言、不连锁。
3. 警长被投出：开枪结算后移交警徽或撕毁。

### 死亡结算链

夜死与放逐共用一个链条（`flow._resolve_chain`）：**只有本轮真实发生死亡（存活→死亡）的座位**才触发开枪/移交，
且被枪杀者不连锁。放逐链另用 `last_exile_was_alive`（投票前的存活标记）守门——
幻觉座位或「本就已死」的座位不会被写入 `alive` 表，也不会重复发遗言/刷枪。

## 五、胜负

**好人胜**：狼人全部出局。

**狼胜**（满足任一）：

1. 神职（预言家/女巫/猎人）全部出局（屠边）；
2. 平民全部出局（屠边）；
3. 存活狼数 ≥ 存活好人数（屠城）；
4. 第 `max_days` 天（默认 8）**白天流程走完**后仍有狼存活。

> 时限口径（回归 M4）：`day` 在入夜时自增，`day=N` 覆盖第 N 夜与第 N 天白天；
> 时限条件是「`day >= max_days` 且第 `max_days` 天的放逐结算已结束」，
> 不会出现「第 8 天白天还没打就判狼胜」。

## 六、规则切片（按步骤注入，D12）

| 切片键 | 内容 | 注入时机 |
|---|---|---|
| `overview` | 阵营、人数、胜负条件、240 字上限 | 每次调用（稳定段） |
| `night_wolf` | 频道礼仪、定刀多数决、空刀语义 | `wolf_meeting` / `closing` |
| `night_seer` | 查验语义与保密义务 | `seer_check` |
| `night_witch` | 双药各一、每晚一瓶、刀口信息、不挡毒 | `witch_turn` |
| `gun_skill` | 开枪条件（非毒死）、不连锁 | `gun` |
| `sheriff_elect` | 上警/宣言/投票/PK/丢徽 | `sheriff_elect` / `sheriff_register` |
| `sheriff_power` | 2 票权重、归票、移交/撕毁、定序 | `speech_order` / `day_speech` / `day_vote` / `badge` |
| `day_speech` | 发言秩序与上限 | `day_speech` / `serial_speech` / `last_words` |
| `day_vote` | 投票资格、平票 PK、遗言 | `day_vote` / `ballot` / `exile_resolve` |

## 七、记忆层投影（`definition.memory_line`）

记忆层是「本座可见事件的历史投影」，**凡本座可见的事件都必须有落点**（D26）：

| 事件 | 记忆行 |
|---|---|
| `player.speech` / `channel.message` / `player.last_words` | `<speech seat="n">…</speech>` 围栏包裹（遗言加「（遗言）」前缀；内容里的尖括号与行首 `#` 会被中和，防注入） |
| `phase.started` | `【第 N 天·阶段中文名】` |
| `day.speech_order` | `本轮发言顺序：2 号→3 号→…。` |
| `match.started` / `match.finished` | `对局开始。` / `对局结束：好人阵营获胜（原因）。` |
| `night.resolved` | `第 N 夜：X 号 死亡。` / `平安夜，无人死亡。` |
| `night.seer_result` | `你查验了 X 号玩家：阵营是【狼人/好人】。` |
| `vote.cast` | `X 号投给了 Y 号。` / `X 号弃票。` |
| `vote.resolved`（scope=exile） | `第 N 天放逐投票：X 号出局。` / `平票，无人出局。` |
| `vote.resolved`（scope=sheriff） | `警长投票结果：X 号当选警长。` / 平票 |
| `sheriff.registered` | `上警报名：…` / `无人上警。` |
| `sheriff.badge` | `警徽归属：X 号。` / `警徽被撕毁，本局再无警长。` |
| `gun.shoot` | `X 号开枪带走了 Y 号。` / `放弃开枪` |
| `skill_state.notice` | `你的技能状态：可以/不能开枪。` |

刻意不落点（信息已由其它层给出，重复只会灌水）：`role.dealt`（身份层已声明角色）、
`night.started`（紧随的 `phase.started` 已给「第 N 天·入夜」）、`match.created`（`match.started` 覆盖）。

## 八、可见性（`definition.visibility` 是唯一权威）

| 事件 | 可见性 |
|---|---|
| `night.kill_target` / `night.witch_action` / `night.death_cause` / `channel.round.*` / `player.monologue` / `player.fallback` | god |
| `channel.message` | seat = 存活狼队成员 |
| `night.seer_result` | seat = 预言家本人 |
| `skill_state.notice` / `role.dealt` | seat = 本人 |
| `player.speech` / `player.last_words` / `night.resolved` / `vote.*` / `gun.shoot` / `sheriff.*` / `day.speech_order` / `match.*` / `phase.*` | public |

## 九、待确认（按面杀惯例暂定，用 ※ 标记）

1. 同刀同毒的死因认定（※ 未救按刀杀可开枪、已救按毒杀不可开枪）。
2. 女巫刀口信息时机的原文歧义（※ 按「用药时知晓，解药用尽后不再告知」落地）。
3. 枪杀目标若为猎人可否连锁开枪（※ 暂定不可：一次死亡一次开枪）。

（守卫悖论已随守卫角色一起移除，原「同守同救」条目不再适用。）
