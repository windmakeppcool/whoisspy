# 游戏插件契约（多游戏扩展边界）

新游戏 = 实现 `GameDefinition` + 注册 + 写规则切片 + 提供 boards 预设。engine / agents / storage 不为具体游戏改动；若必须改，说明本契约有缺口，**先修订本文档再动代码**。

抽象只覆盖「阵营制 + 隐藏身份 + 轮流发言 + 投票」这一族（狼人杀、谁是卧底、阿瓦隆等），不做万能游戏引擎。

## GameDefinition（games/base.py）

```python
class GameDefinition(Protocol):
    game_type: str

    # 配置与发牌
    def validate_board(self, board_cfg: dict) -> BoardSpec: ...
    def deal(self, spec: BoardSpec, rng: random.Random) -> list[RoleAssignment]: ...

    # 状态机（Reducer，支柱 1）
    def initial_state(self, spec: BoardSpec, roles: list[RoleAssignment]) -> GameState: ...
    def next_step(self, state: GameState) -> Step: ...
    def apply(self, state: GameState, event: Event) -> None: ...

    # 动作与规则
    def action_schema(self, step: Step) -> ActionRequest | None: ...
    def validate_action(self, state: GameState, seat: int, action: dict) -> dict: ...
    def check_winner(self, state: GameState) -> GameResult | None: ...

    # 可见性唯一权威（支柱 3）
    def visibility(self, draft: Event, state: GameState) -> VisMeta: ...

    # 规则切片注入（D12）
    def rule_slices(self) -> dict[str, str]: ...        # 切片键 → 规则文本
    def slices_for(self, step: Step) -> list[str]: ...  # 该步骤需要的切片键（含 overview）
```

约束：

- `deal` / 计票 / 平票等一切随机必须走传入的带种子 `rng`，且结果写入事件——保证确定性重放与未来分叉重跑（支柱 1）。
- `apply` 是纯归约：同事件流必须重建出同状态（有单测锁死 `apply 重放 ≡ 直接构造`）。
- `visibility` 是**唯一**可见性权威：事件入库前由它标注 `vis_level`（public / seat / god）与 `vis_seats`，出站过滤只认这份元数据。
- `rule_slices` 的切片组织示例：`overview`（阵营与胜利条件）、`night_wolf`（狼队频道与定刀）、`night_seer`（验人）、`day_speech`（发言秩序）、`day_vote`（计票与平票）。`slices_for` 按当前 Step 选取，配合 [agents-and-llm.md](agents-and-llm.md) 六层拼装的规则层。

## Step 原语（engine/steps.py，插件可组合的全部积木）

| 原语 | 语义 | 典型用途 |
|---|---|---|
| `ChannelMeeting(channel_id, members, topic, rounds, closing_action)` | 私密频道多轮串行商量 + 收尾动作 | 狼队夜间商量定刀 |
| `SoloAction(actor, request, outcome_visibility_seats)` | 单人私密决策，结果按指定座可见 | 预言家验人 |
| `SerialSpeech(speakers)` | 按序轮流公开发言 | 白天发言（节目效果核心） |
| `Ballot(voters, candidates, tie_policy)` | 并行收集投票防跟票，按策略结算平票 | 白天放逐投票 |

游戏的状态机用这 4 个原语编排（`next_step` 产出 Step），结算规则写在游戏插件内；不新增原语类型，除非至少两个目标游戏都需要（防抽象泄漏）。

补充执行语义：

- **夜间并行**：同夜多个 SoloAction（守卫/狼刀/验人/用药）互不通气、可并行收集；狼队内部先经 ChannelMeeting 商量再收刀（并行提案多数决）。
- **复合动作**：ActionRequest 支持「choice + target」组合（女巫：救/毒/不用药；警长：顺/逆时针、移交/撕毁；猎人/狼王：开枪目标/不开枪），`validate_action` 校验合法性（禁连守、药数、开枪资格、目标存活等）。
- **Ballot 的 tie_policy**：`random`（带种子随机）、`no_exile`（平安日/丢徽）、`pk_then_no_exile`（PK 发言后重投，仍平则平安日——PK 由状态机编排 SerialSpeech + 二次 Ballot，非原语内建）。
- **结算链**：死亡结算后的连锁技能（开枪→枪杀、警徽移交）由状态机展开为后续 Step，每死一档立即 check_winner。

## 新游戏接入清单

1. `games/<name>/definition.py` 实现 GameDefinition（含规则切片）。
2. `games/<name>/rules.py` 纯函数：发牌校验、计票、胜负、结算。
3. `games/<name>/state.py` 状态定义 + `apply` 归约。
4. `games/registry.py` 注册 `game_type`。
5. `boards.json` 增该游戏板子预设（[configuration.md](configuration.md)）。
6. 测试：规则纯函数单测 + `apply` 重放等价 + mock 整局（[milestones.md](milestones.md) 测试策略）。
