# 游戏插件契约（多游戏扩展边界）

新游戏 = 实现 `GameDefinition` + 注册 + 写规则切片 + 提供 boards 预设 + 实现 `flow.py` 步内流程。
**engine / agents / storage 不为具体游戏改动**；若必须改，说明本契约有缺口，先修订本文档再动代码。

抽象只覆盖「阵营制 + 隐藏身份 + 轮流发言 + 投票」这一族（狼人杀、谁是卧底、阿瓦隆等），不做万能游戏引擎。

> 当前只有 `werewolf`（唯一板子 standard-9）一个插件，见 [games/werewolf.md](games/werewolf.md)。
> 单板收敛见 [decisions.md](decisions.md) D23。

## 一、GameDefinition（games/base.py）

```python
class GameDefinition(Protocol):
    game_type: str

    # 配置与发牌
    def validate_board(self, board_cfg: dict) -> BoardSpec: ...
    def deal(self, spec: BoardSpec, rng: random.Random) -> list[RoleAssignment]: ...
    def initial_state(self, spec: BoardSpec, roles: list[RoleAssignment]) -> GameState: ...

    # 状态机（Reducer，支柱 1）
    def next_step(self, state: GameState) -> Step: ...       # kind 由插件自定义
    def apply(self, state: GameState, event: Event) -> None: ...

    # 动作与规则（合法性的唯一权威）
    def action_schema(self, state: GameState, step: Step) -> ActionRequest | None: ...
    def validate_action(self, state: GameState, step: Step, seat: int,
                        action: dict) -> dict: ...
    def neutral_action(self, state: GameState, step: Step) -> dict: ...
    def check_winner(self, state: GameState) -> GameResult | None: ...

    # 可见性唯一权威（支柱 3）
    def visibility(self, event: Event, state: GameState) -> VisMeta: ...

    # 规则切片注入（D12）
    def rule_slices(self) -> dict[str, str]: ...
    def slices_for(self, step: Step) -> list[str]: ...

    # 步内流程（游戏规则的唯一归属地）
    async def play(self, ctx: StepContext, step: Step) -> None: ...

    # engine 不认识的语义：记忆层投影 / 阶段天数
    def memory_line(self, event: Event) -> str | None: ...
    def phase_day(self, state: GameState, step: Step) -> int: ...
```

约定：

- `deal` / 计票 / 平票等一切随机必须走传入的带种子 `rng`（`ctx.rng`），结果写入事件——保证确定性重放。
- `apply` 是纯归约：同事件流必须重建出同状态（有单测锁死「apply 重放 ≡ 直接构造」）；
  插件私有状态放 `state.extra`，**只能由 `apply` 修改**（如入夜清空动作收集是 `night.started` 事件驱动的）。
- `visibility` 标注 `vis_level`/`vis_seats`；出站过滤只认这份元数据（`core.filtered_view`）。
- `validate_action` 必须把非法动作降级为 `neutral_action` 的结果——engine 不再做任何游戏语义校验。
  步骤参数 `step` 必须传入：动作类型集合与**合法目标候选集**都按 `step` 判定
  （候选集取 `step.params["candidates"] ∩ 存活`；子步骤如竞选报名/收刀/开枪各有自己的 kind）。
  插件代码抛异常不会被当成「LLM 调用失败」：engine 会落 god 级 `plugin.error` 并回落通用中性动作。
- `neutral_action` 是**必须实现**的契约方法：它给出该步骤真正中性的动作，
  **绝不能替玩家做决定**（女巫步的 `action_type` 是 save，但兜底必须是 `pass`，不能用掉解药）。
  插件未实现时引擎会回落「请求类型 + target 0」的通用兜底并打印一次告警——对「用药/开枪」类动作并不中性，
  只作为最后防线。
- `memory_line` 返回 prompt 就绪的一行；返回 `None` 表示该事件不进记忆。

## 二、StepContext：engine 提供的 IO 原语（engine/context.py）

插件在 `play` 里只通过 ctx 与外界交互。engine 不暴露 runner 内部，也不认识任何游戏事件。

| 原语 | 语义 |
|---|---|
| `ctx.state` / `ctx.spec` / `ctx.rng` / `ctx.step` | 只读状态、板子规格、对局级带种子随机源、当前步骤 |
| `await ctx.emit(type, payload=None, vis=None)` | 落事件（seq 单写者）并立即归约到状态 |
| `await ctx.ask(seat, request, purpose="…", step=None)` | 单座位调用，返回 `(action, resp)`；`step` 决定校验规则与规则切片 |
| `await ctx.ask_many(seats, request, purpose="…", step=None)` | 并行收集多座位（互不通气），逐座位补落独白 |
| `await ctx.speech(seat, request, channel=False, purpose="…", step=None)` | 一次发言：落 `player.speech`/`channel.message` + 独白 |
| `await ctx.collect_ballot(voters, candidates, title=…, step_kind=…)` | 并行收票（防跟票），逐票落 `vote.cast`，返回 `voter→target` |
| `await ctx.monologue(seat, resp)` | 需要手动补落独白时使用 |

**计票规则在插件里**（engine 不认识警长 2 票权重）；`collect_ballot` 只负责收票与落 `vote.cast`。

引擎侧通用职责（插件不需要也不应该实现）：事件写入与 seq、`apply` 调用、可见性标注时机、
prompt 六层拼装与记忆投影、调用容错链（重试/坏 JSON 修复/中性兜底）、步级超时、终止语义。

## 三、状态机与步骤

`next_step(state)` 返回 `Step(kind, params)`：

- `kind` 由插件自定义（engine 不认识具体值），`params` 供插件自用（如 `speakers`）。
- `kind == "noop"` 表示「没有可执行步骤」：引擎会再查一次胜负，仍未分胜负则判为状态机停摆（status=stopped）。
- 引擎在每步前落 `phase.started`（`phase=kind`、`day=phase_day(state, step)`），并做步级超时兜底。

「4 原语」的现代形态就是上面的 `ctx` 方法（并发/串行语义由插件组合），不再有 `engine/steps.py`。

## 四、新游戏接入清单

1. `games/<name>/rules.py`：纯函数——板子校验、发牌、计票、结算、胜负。
2. `games/<name>/definition.py`：`GameDefinition` 实现（状态机、动作 schema/校验、可见性、记忆行、切片）。
3. `games/<name>/flow.py`：`play` 的步内流程（用 ctx 原语编排）。
4. `games/<name>/prompts.py`：规则切片文本。
5. `games/registry.py` 注册 `game_type`；`backend/data/boards.json`（或内置 `PRESETS`）加板子预设。
6. 测试：规则纯函数单测 + `apply` 重放等价 + mock 整局 + 架构约束
   （`tests/test_architecture.py` 会检查 engine 里不得出现任何具体游戏痕迹）。
