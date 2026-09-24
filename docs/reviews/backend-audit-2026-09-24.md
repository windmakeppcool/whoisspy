# 后端实现审查报告（2026-09-24）

审查范围：`backend/`（app / scripts / tests）的正确性、健壮性，以及与 `docs/` 设计契约的一致性。

方法：通读全部后端源码与设计文档；确认测试基线（`227 passed in 68s`，无 flaky）；
每条关键结论都用一次性脚本在 `backend/.venv` 里实测复核（脚本只写在系统临时目录，**未改动仓库任何文件**）。
另有一次独立对抗性验证（专门构造幻觉动作/并发/异常注入场景）用于交叉确认。

结论标记：

- **实测** = 我用脚本跑出过具体输出，可复现；
- **代码** = 由源码直接可判定；
- **文档** = 与 `docs/` 契约不符。

---

## 一、严重：对局正确性（狼人杀标准局基本跑不对）

### X2 当选警长会被 reducer 当场判死（标准局核心机制失效） **实测**

`_exec_ballot` 无条件发 `vote.resolved`（`runner.py:492-493`），警长选举票也走这条路径；
而 `apply` 只认 `payload.exiled`、不看标题（`definition.py:216-219`）：

```python
elif t == "vote.resolved":
    exile = p.get("exiled")
    if exile:
        state.alive[int(exile)] = False      # ← 当选警长被当成被放逐者
```

实测（standard-9，MockLLM，seed=5/11/23/42 四局全部复现）：当选警长 = 1 号，
该座位**唯一的死亡类事件就是「警长投票」这条 `vote.resolved`**，终局 `alive[1] = False`。

连锁影响（**代码**可判定）：

- 警长此后不再发言、不再投票（`day_speech`/`day_vote` 的 voters/speakers 都取 `alive`）→ 2 票权重、归票权全部作废；
- 若警长是神职，`check_winner_standard` 的神职/平民计数少 1 → 屠边/屠城条件提前满足，**直接改写胜负**（实测 seed=23 得到「存活狼 3 ≥ 存活好人 3（屠城）」，把警长改回存活则 `check_winner=None`，本该继续）；
- 记忆层把这条事件渲染成「第 N 天放逐投票：1 号玩家出局。」（`runner.py:168-172` 不区分标题）→ **全桌 agent 都被告知警长已被放逐**，信息被污染；
- 测试没红：`test_full_match_mock.py` 只断事件类型齐全 / seq 连续 / 胜负属于 {wolf,good}，没有任何「警长存活」断言。

修复方向：选举票不要复用 `vote.resolved`（换成 `sheriff.vote_resolved` 一类独立事件），
或在 `apply` 里按 `purpose/title/scope` 区分归约分支；并补「当选警长存活」的回归测试。

### X1 警长首轮平票走 PK 时必崩（整局异常终止） **实测**

`runner.py:281-282`：

```python
for s in tied:  # PK 发言
    if st.alive.get(s) and sp_req is not None:
        await self._speech_round(s, sp_req, "sheriff_speech", channel=False)  # ← 缺 step
```

`_speech_round(self, seat, request, purpose, channel, step)` 的 `step` 无默认值（同函数 `:271-272` 传了 `step=sp_step`）。

实测（1/2/3 上警，未上警的 4..9 号 3:3 投 1/2 → 首轮平票）：

```
run() 抛出: TypeError: MatchRunner._speech_round() missing 1 required positional argument: 'step'
   File ".../app/engine/runner.py", line 282, in _exec_sheriff_elect
事件数 35 | 有 match.finished: False | sheriff 事件: [sheriff.registered] | 选举投票: ('警长投票', None, True, [1,2])
```

`run()` 只捕 `asyncio.TimeoutError`，异常直接冒到 `api/app.py:150-154` 只把 status 改成 stopped；
直接跑脚本（`scripts/run_match.py`/`e2e_real.py`）则 status 永远停在 `running`。
触发面 = 首轮平票 **或** 全弃权（`tied=[]` 回落 `registered`，`runner.py:279` 后走同一循环）——
真实 LLM 局平票概率不低。现有测试全用 MockLLM（启发式恒投最小候选，永不产生平票），所以从未触发。

### S1 手动停止的对局被写成「狼人胜利 + finished」 **实测**

`runner.py:583-611`：stop 分支把 `result` 设成 `GameResult(winner="wolf", reason="对局被手动终止")`，
而收尾是 `if result is not None: … emit(match.finished) + update_match(status="finished")`，
`elif self._stop.is_set(): update_match(status="stopped")` **永远不可达**（所有 break 路径都设了 result）。

实测：`DB status = finished`、`DB result = {'winner': 'wolf', 'reason': '对局被手动终止'}`，
事件流同时出现 `match.stopped` 与 `match.finished`。历史列表/复盘页会把中途终止的对局显示成狼人胜利。

修复方向：stop 独立分支只落 `match.stopped`；需要一个能表达「无胜者」的 Result 类型；删掉不可达的 `elif`。

### S2 女巫永远拿不到刀口信息（解药决策 100% 盲选） **实测**

`definition.py:140-142` 把刀口写进 `ActionRequest.extra`（`night_kill/has_save/has_poison`），
但 `agents/protocol.py:build_user_prompt` 只渲染 `prompt + candidates + action_type`；
`request.extra` 在全 app 内 **0 个消费点**（grep `request.extra`/`night_kill` 无生产命中）。

实测（standard-12，当晚刀口 = 7 号）：女巫 prompt 里既无「7 号」，也无 `night_kill` 字样。

`docs/games/werewolf.md:52` 明确要求「女巫行动请求中，解药尚在则附当晚刀口供决策」——
该机制实际不存在，女巫只能瞎猜，直接抹掉一个关键观赏点（救/不救、毒/不毒的博弈）。
修复方向：`build_user_prompt` 支持 `extra` 的结构化渲染（易变段，落在指令层），或把刀口做成本人可见的记忆行。

### S3 调用失败时兜底动作会替女巫吃掉解药，甚至凭空致人死亡 **实测**

`faults.py:13` 兜底 = `{"type": request.action_type, "target": 0}`，
而女巫步的 `action_type` 就是 `"save"`（`definition.py:136`）；
`runner.py:398-407` 的裁剪只拦「解药已用」，不区分这是兜底。
于是 agent 超时/报错 ⇒ `night.witch_action{act:"save"}` ⇒ `used_save=True, night["saved"]=True`；
若守卫当夜同目标，`rules.py:186-191` 的守卫悖论会再判死一人。

实测（gateway 全部抛 `ConnectionError` 的 standard-9 局）：零次成功调用，女巫仍「用掉」解药 1 次。

违反 `docs/engine.md:35`「用药=不用药；兜底一律取中性动作，绝不替玩家做主」。
修复方向：兜底按语义表返回（用药→`pass`、开枪→0、上警→`false`），
或在 `_exec_witch_turn` 里把兜底动作统一降级为 `pass`。

### S6 `validate_action` 零校验：幻觉目标可以入票/被毒/放出幻影死亡 **实测**

`definition.py:180-187` 只做 `type/target` 强转，连候选集都不比对；
`runner.py:114` 调用后也没有二次校验；`rules.tally_votes` 不校验目标（对比 `decide_kill` 有 `valid_targets`）。
`docs/game-plugin.md:24,56` 要求它校验「禁连守、药数、开枪资格、目标存活」。

实测后果（两个独立验证都复现）：

| 场景 | 结果 |
|---|---|
| 全场投已死 6 号猎人 | 6 号再次发表遗言，`gun.shoot(seat=6)` 出现 **2 次**（第二枪带走 3 号） |
| 全场投不存在的 99 号 | `alive[99]=False` 幻影座位入库；99 号"发表遗言"；导出出现「99号 被放逐」；全桌记忆被污染 |
| 女巫毒已死 7 号 / 毒 99 号 | `deaths{7|99:'poison'}`，记忆层「第 2 夜，99 号死亡。」 |
| 女巫在空刀夜用解药 | 允许，解药白耗 |
| 守卫连守同一人 | 候选集由 `definition.py:144-147` 过滤过，这条反而是对的 |

`_exec_exile_resolve` 的守卫是 `alive.get(exile) is False`（`runner.py:432`），
对「本来就是死人」同样为真，于是死人可以被反复「放逐」刷遗言、刷枪；若该死人仍是警长还会重复移交警徽。
修复方向：`validate_action` 按动作类型校验候选/存活/资格，
`_exec_exile_resolve` 只对「本轮真实发生 True→False 迁移」的座位触发连锁。

---

## 二、严重：契约与健壮性

### S4 生产路径的重试链完全失效（网络/5xx 一次都不重试） **实测**

`gateway.py:229` 只捕获 `(ConnectionError, asyncio.TimeoutError, TimeoutError)`，
生产走 openai SDK（`app.py:142`）且 `max_retries=0`（`gateway.py:177`）。实测 openai 3.19.0：

| 异常 | 继承内置 ConnectionError | TimeoutError | 注入假 inner 后的实际调用次数 |
|---|---|---|---|
| `APIConnectionError` | False | False | **1**（不重试） |
| `APITimeoutError` | False | False | **1** |
| `RateLimitError` | False | False | **1** |
| `InternalServerError` | False | False | **1** |
| 内置 `ConnectionError` / `TimeoutError` | True | True | 3（测试里才重试） |

即 `docs/engine.md:33`「网络/5xx 重试 ≤2（退避 2s/5s）」在生产中从不触发，
任何抖动直接落到兜底（并叠加 S3）；`_raw_complete` 的超时分类同样漏掉 openai 超时，
用量表会把超时记成 `status="error"`。测试没暴露它：`tests/test_agents_llm.py` 注入的是内置 `ConnectionError`。

修复方向：捕获 `openai.OpenAIError` 分层处理（`APIConnectionError/APITimeoutError` 与 429/5xx 重试，
4xx 参数错不重试），或直接启用 SDK 自带 `max_retries=2`。

### S5 引擎与狼人杀深度耦合：插件边界只剩文档 **代码/文档**

`docs/game-plugin.md:3`、`docs/engine.md:3`、`CLAUDE.md` 规则 6 都要求 engine 不为具体游戏改动，但：

- `engine/runner.py:367 / 416 / 479` 函数内 `from app.games.werewolf import rules as wr`，
  直接调用 `wr.decide_kill / resolve_night / tally_votes`——**通用原语 Ballot 用的是狼人杀计票（含警长 2 票）**；
- 硬编码角色名：`:226 hunter/wolf_king`、`:233 guard`、`:341 wolf/wolf_king`、`:376 seer`、`:386/394 witch`；
- 硬编码游戏私有状态键：`:203/316/318 extra["sheriff"]`、`:404/406 used_poison/used_save`、`:415 extra["night"]`；
- 记忆投影 `:150-173` 硬编码狼人杀事件名（`night.seer_result`/`night.resolved`/`vote.resolved`…）；
- 硬编码中文业务串 `:494 if title.startswith("放逐")`（正是 X2 的同源问题）；
- 11 个狼人杀专属 step kind 进入引擎派发（`:182-205`），而 `game-plugin.md:42-51` 定义的 4 原语参数
  （`channel_id/topic/closing_action`、`outcome_visibility_seats`、`tie_policy`）在实现里 **0 命中**，
  `engine/steps.py` 不存在；`channel_meeting/solo_action/resolve` 三类 kind 在狼人杀流程里从不出现（死代码路径）。

修复方向（择一，并同步文档）：(a) 把结算/计票/记忆渲染下沉为 `GameDefinition` 的新方法；
(b) 承认现状，重写 `game-plugin.md` 的原语章节——不要让文档承诺做不到的事。

---

## 三、中等

### M1 记忆层漏事件：模型看不到票型、警徽归属、开枪结果 **实测**

`runner._memory_line` 只渲染 6 类事件。实测 standard-12 整局，对某座位**可见但记忆层丢弃**：

| 事件 | 出现次数 | 影响 |
|---|---|---|
| `vote.cast` | 43 | 「盘票型」策略（`defaults.py` 明写）完全无法执行 |
| `sheriff.badge` | 7 | 模型不知道谁是警长（2 票权重、归票无从谈起） |
| `gun.shoot` | 2 | 不知道有人被枪杀 → 死讯出现无法解释的缺口 |
| `sheriff.registered` | 1 | 不知道谁上过警 |

`docs/agents-and-llm.md:41` 承诺的是「本座可见的事件历史投影（按可见性过滤后）」，
即逐事件投影；实现却是引擎里的白名单裁剪（同时也是 S5 的证据）。
修复方向：把记忆行渲染交给游戏插件（`memory_line(event)`），未识别类型给通用兜底行而非静默丢弃。

### M2 放逐投票的平票 PK 没实现（警长 PK 反而实现了） **实测/文档**

`docs/games/werewolf.md:128,174,177`、`game-plugin.md:57` 要求「平票 → PK 发言 → 全体重投 → 仍平票平安日」；
`definition.py:100-101` 是 `day_vote → exile_resolve` 直连，`runner.py:429-440` 平票直接跳过。
实测白天平票：`{'exiled': None, 'tie': True, 'tied': [1,2]}` → 直接平安日，无 PK 无重投。

修 X1 之后还要一并处理警长 PK 的口径：`runner.py:283-285` 的 `voters=alive` 把平票者本人算进投票人，
与 `werewolf.md:108`「**其余**所有玩家（含已上警者）」相反（反事实验证：排除平票者时结果为平票丢徽，
按现实现则是平票者自己给自己投票而当选）；
`tied=[]`（全弃权）回落到 `registered` 也属隐式语义，建议显式化并写测试固定。

### M3 白天发言秩序机制整体缺失 **文档/代码**

`docs/games/werewolf.md:120-122` 要求「有警长由警长定序、无警长 rng 随机起点」，
`runner.py:196-199` 固定 `sorted(alive)` 升序，不查 sheriff、不用 rng；竞选宣言同样升序（`:269`）。
`definition.slices_for` 里 `sheriff_power` 只在 `badge` 步注入，白天发言/投票步拿不到警长规则
（文档 `werewolf.md:199` 说「白天各步」）。

### M4 天数上限早生效一整个白天，且结束原因文案不实 **实测**

`state.day` 在 `phase.started(night_start)` 时自增（`definition.py:194-197`），胜负检查在每步之前
（`runner.py:587-590`），`rules.py:237` 用 `day >= max_days`。

实测（全员弃权／空刀拖到时限）：对局在 **第 8 夜开始**（第 7 天白天刚结束）就结束，
reason 写「第 8 天结束仍有狼存活」，但第 8 天白天从未发生；有效上限实际是 7 个完整白天。

### M5 沉浸视角能看到死因 **文档/代码**

`runner.py:414-418` 把 `resolve_night` 的 `{seat: "poison"|"knife"}` 原样放进 **public** 的 `night.resolved`；
过滤是事件级的（`repo.py:191`），无法剔字段。
`docs/events-storage.md:19` 写明「不报过程与死因；payload 含死因供 god 复盘」、`werewolf.md:114`「死因不公布」——
沉浸视角因此泄露 god 级信息（且死因不进记忆层，观众比玩家多知道信息）。

### M6 费用统计恒为 0 **代码/文档**

`gateway.py:204-212` 与 `MockLLM` 都硬编码 `cost_micros=0`；`price_per_mtok_in/out` 在 `app/` 内 0 命中。
`docs/agents-and-llm.md:76` 与 `milestones.md` M1 验收「费用与 llm_call 汇总一致」未达成。
另：`llm_call.ref_event_seq`（文档称 `ref_event_id`）从不写入，永远 NULL。

### M7 历史对局的人设不可复现；真实跑局入口丢人设 **文档/代码**

`docs/events-storage.md:35`/D10 声明 `match_seat` 固化 persona_id、style、strategy、单价；
`storage/models.py:34-45` 只有 seat/name/persona_id/base_url/api_key_env/model/role。
style/strategy 每次开跑从**当前** `personas.json` 现取（`app.py:121-127`），改配置后老对局无法还原。
另：`scripts/e2e_real.py:71-76` 与 TUI `--real` 把 style/strategy 写死为空串，
真实跑局跑的是**无人设无策略**的裸模型，与 API 路径行为不一致（D11 承诺「风格可感知」）。

### M8 POST /api/matches 输入校验缺失（座位号） **实测**

`app.py:93-96` 只比对座位**数量**，不校验座位号唯一性与范围：

- 6 个座位全传 `seat=1` → HTTP 200；`match_seat` 6 行全是 seat=1 且 role 全被写成同一角色
  （`set_seat_roles` 按 `s.seat in roles` 回填，全部命中 `roles[1]`），`seat_meta` 塌缩成 1 个键，
  但事件流里 6 个 `role.dealt` 指向 1..6 号——**对局记录自相矛盾**；
- 传 `seat ∈ {0,-1,7,8,9,10}` → HTTP 200；发牌仍是 1..6，座位表与角色完全错位；
- 未知 `persona_id` → 静默回落到 `personas[0]`（实测 `NO_SUCH_PERSONA` 落库，运行时用第一个人设）；
- `api_key_env` 解析不到 key 时不报错，整局静默走兜底（`scripts_helpers/e2e.py:57-60` 是会报错的）；
- `game_type` 不参与游戏解析（`app.py:90` 用 board 解析），只被写库，可写出与实际运行不符的 game_type。

### M9 API 契约与实现不一致 **实测**

- `docs/api.md:27-43` 的 seats 示例**没有 `seat` 字段**，但 `app.py:29` 是 `seat: int` 必填 →
  按文档构造请求直接 422；文档承诺的 `provider_ref` 写法**未实现**（实测：带 `provider_ref` 且无 seat → 422；
  存在 `provider_ref` 时被 Pydantic 静默忽略 → 落到 mock，跑出零成本假局）。
- `events-storage.md:49` 说重连带 `Last-Event-ID` **头**，实现只认 `last_event_id` **查询参数**
  （`app.py:181-183`；api.md:55 与 D16 是查询参数口径）——文档内部互相矛盾，TUI 客户端发的头是死代码。
- `api.md:57` 的「immersive = public + 本视角 seat」没有实现路径。
- `match.created`、`phase.ended`、SSE `event: error` 帧均未实现；`/export` 已实现但未进 api.md 端点表。

### M10 运行生命周期与 seq 分配

- `app.py:147-159` 用 `create_task` 起 runner，task 不保存、关停时不取消/不等待；
  lifespan `close()` 直接 dispose 引擎，正在跑的对局可能往已关闭的引擎写事件（测试靠刚巧跑得快掩盖）；
  `stop_flags` 永不清理（`app.py:63,129`）。异常退出后 match 可能停在 `running`（X1 在脚本入口即如此）。
- **`game_event.seq` 无唯一约束**（`models.py:53` 只有普通索引），seq 由 storage 用**实例级** `asyncio.Lock`
  + `MatchRow.current_seq` 读改写分配（`repo.py:92,163`），且与 `engine.md:7`「seq 由 MatchRunner 分配」描述不符。
  实测：单实例 300 并发 → seq 1..300 唯一连续（没问题）；**两个 repo 实例并发 60 次 → 只有 30 个唯一 seq，重复静默入库**
  → 会导致 SSE 游标（`app.py:196-211` 用 `after_seq`）漏推、`ORDER BY seq` 顺序不稳。
  单进程单写者下安全，属于部署约束（`uvicorn --workers N` / 双实例会踩），建议加 `UNIQUE(match_id, seq)`
  或把自增下沉到 DB。

### M11 安全：无鉴权 + CORS 全开 + 座位可自定义 base_url/api_key_env **代码**

后端绑 127.0.0.1，但 `app.py:57-58` 的 CORS 是 `allow_origins=["*"]` 且无任何鉴权令牌。
结合 `SeatIn` 允许客户端自带 `base_url`（D10「座位级独立 key」）：

1. 任意网页在用户浏览器里 POST `http://127.0.0.1:8000/api/matches`（预检被 `*` 放行），
   把某座位 `base_url` 指向攻击者地址、`api_key_env` 填一个常见变量名，
   后端就会 `resolve_api_key()` 取出**真实 key 并作为 Bearer 发给攻击者地址**（`app.py:119-127` + `gateway.py:176`）；
2. 同样可以 `GET /api/matches/*/events?view=god` 与 `/export`，把上帝视角内容（独白、狼队密聊）整局拉走。

本地观赛工具里这仍值得修：只接受 providers.json 中的 provider（不接裸 base_url）、CORS 收敛到前端源、
加本地 token；另外 `POST /{id}/stop` 对不存在的对局也返回 `{"ok": true}`、`GET /{id}/usage` 不校验存在性。

---

## 四、轻微 / 卫生

- **潜伏（当前不可达）**：`resolve_night` 用 `guard == kill` 判守卫命中（`rules.py:187`），
  而 0 是「空刀/空守」哨兵——若 kill 真为 0 会造出 `deaths[0]` → `apply` 写入 `alive[0]`（幻影）+
  记忆层「第 N 夜，0 号死亡」+ `/export` 500（`dialog.py:93` `"、".join` 里含 `_seat_str(0)==None`）。
  实测确认 kill=0 在现有状态机中不可达（唯一生产者 `runner.py:342-344` 的 no_wolf 分支，
  在存活狼=0 时必已被 `check_winner` 终结），所以是潜伏点；建议 `kill not in (None, 0)`、`alive` 写入前做 `roles` 白名单、
  `_seat_str` 返回占位串。
- `app.py:95-96` 遗留死代码 `detail=... if False else ...`（`spec.player` 根本不存在）；
  `runner.py:357-364` `import asyncio as _a`、`repo.py:161` `import asyncio as _asyncio` 冗余；
  `repo.py:145,166` 用 `assert` 做运行期校验（`-O` 下消失）。
- `core.filtered_view` 是死代码（生产过滤在 `repo.py:191`），与 `events-storage.md:30`「同一过滤函数服务 REST 与 SSE」不符；
  两处规则目前等价、无泄露，但将来容易漂移。
- `runner.py:415` 直接 `state.extra["night"]` 下标（键缺失即 KeyError）；
  `definition.visibility` 是「默认 public」白名单，新增事件漏登记就默认公开；
  `_emit` 的显式 `vis` 参数会被插件覆盖（如引擎给 `gun.shoot` 传 god，实际落 public），两处真相源容易误判。
- 双预言家板子（minimal 允许 seers 0-2）只驱动**座位号最小**的预言家，另一个整局不查验
  （实测 6 人 2 预局全场只有 1 个 `night.seer_query`）。
- `phase.started` 事件的 `day_index/phase` 用的是**上一步**的值（`runner.py:592-595` 先 emit 后更新）：
  实测首夜记成 `day_index=1, payload.day=0`，第二夜记成 `day_index=1`；`export/dialog.py` 按 `ev.phase` 分段，
  导出会多出/错位分段（首个「第一天」段落实际装的是夜晚事件）。
- `match.started.payload.seed` 是从发牌用的同一个 RNG 里抽的随机浮点（`runner.py:561`），不是真实种子，
  且这次抽取会前移发牌序列（外部按 rng_seed 复算发牌会得到不同结果，容易误导）。
- `Stop` 语义：`runner.py:584` 用 `winner="wolf"` 表达「终止」，`GameResult.winner` 只有 wolf/good 两值——
  类型上就没有「无胜者」，是 S1 的根因。
- 测试卫生：`backend/tmp*/`、`backend/pytest-of-*/` 临时目录会落在仓库工作区（`git status` 可见），`.gitignore` 未覆盖；
  `tests/test_engine.py` 用 `spec=None` 跑通，靠 `runner.py:563-572` 用 `type("S", (), ...)` 伪造 spec 的兼容分支，
  建议把 `spec` 改为必填。
- 文档层面未实现/未更新：`api_key_file`（`configuration.md:88`）、`architecture.md` 的目录结构与 `EventBroker`、
  `ref_event_id` 命名、`configuration.md:23` 与 D17 关于 `api_key_env` 是否外泄的表述冲突。

---

## 五、已确认没问题的部分（抽样）

- 测试基线 227 passed；事件落库链路 `visibility → append（锁内 seq 读改写）→ apply` 顺序正确，
  单实例 300 并发下 seq 连续唯一、payload 无丢失。
- 可见性矩阵：`channel.message` 只对狼队、`role.dealt` 只对本人、`night.*`/`monologue`/`fallback` 仅 god，无越权泄露；
  他人发言以 `<speech seat="n">` 围栏 + 「指令禁读区」声明确实进了 prompt。
- Prompt 六层顺序、记忆 append-only、本步规则切片落在记忆之后、`monologue → speech → action` 字段顺序，
  与 `agents-and-llm.md` 一致（D21/D22 已落地）。
- 狼人杀纯函数层面：发牌校验边界、结算矩阵（同守同救=knife、同刀同毒=knife、毒不可挡、空刀平安夜）、
  定刀多数决 + 平票 rng + 非法目标空刀、standard-9 自动跳守卫、胜负四路径、警长 2 票权重、
  禁连守候选过滤，均与 `docs/games/werewolf.md` 一致（问题是这些规则没被引擎正确地串起来）。
- 密钥安全：`match_seat` 只存变量名、key 仅进程内、仓库无明文、`.env` 与 `backend/data/` 均被 gitignore 且未跟踪。
- 存储：全部查询走 SQLModel/SQLAlchemy 参数化，无 SQL 注入面；`busy_timeout` 看似只在 init 连接设置，
  实测由 aiosqlite/sqlite3 的 `connect(timeout=5.0)` 默认覆盖到所有连接（写锁等待实验与交叉写压测 0 错误），**不是问题**。
- 坏 JSON 的一次格式修复链本身工作正常（实测 2 次调用后抛 `ValueError` 交给上层兜底）。

---

## 六、建议的修复顺序

1. **X2 / X1**：标准局的警长机制现在是坏的（当选即判死 + 平票必崩），且都被测试盲区遮住——
   先补「当选警长存活」「首轮平票→PK→再平票丢徽」两条失败测试，再修。
2. **S1 / S2 / S3**：`match.status` 语义、女巫刀口、中性兜底，改动小、收益大。
3. **S6 + M8 + M9**：动作/输入校验与 API 契约，直接决定真实 LLM 局可用性。
4. **S4**：重试链换 openai 异常类型（顺带修用量表 status 分类）。
5. **M1 + M2 + M3 + M4**：玩法完整性（票型记忆、平票 PK、发言秩序、天数上限）。
6. **S5 + M10 + M11**：架构边界与运行/安全（结算与记忆下沉给插件，或改文档承认现状；runner task 纳入 lifespan；
   API 收紧 origin / 不接裸 base_url）。
7. 其余轻微项按需清理。

> 本报告只做问题定位（成文于修复之前）。逐条都按仓库的 TDD 约定先写失败测试再修。
> 复现脚本在系统临时目录（`%TEMP%\ws_audit\`、`%TEMP%\wsv\`），可直接重跑。

---

## 附：修复状态（2026-09-24 当日完成）

用户决策：**先收敛配置面，再全量修复**（决策记录 D23–D27）。范围与结果：

| 项 | 修复方式 | 验证 |
|---|---|---|
| 前置：配置面收敛 | 只保留 `standard-9` / `p9-standard`，删除 minimal、standard-12、守卫、狼王（D23） | `test_rules_werewolf`、`test_full_match_mock::TestBoardRestriction` |
| X1 警长 PK 崩溃 | `flow._sheriff_elect` 的 PK 发言显式传 `step` | `test_voting_flows::TestSheriffPk` |
| X2 当选警长被判死 | `vote.resolved` 增 `scope`，`apply` 只对 `scope=exile` 判死（D27） | `test_actions_werewolf::TestApplySafety`、`test_full_match_mock::test_当选警长继续投票`、前端 `project.test.ts` |
| S1 stop 语义 | 终止/超限/停摆统一 `match.stopped` + `status=stopped` + `winner=null`（D27） | `test_engine::test_手动终止落stopped不假造胜负` |
| S2 女巫刀口 | `ActionRequest.prompt_extra` 渲染进指令层（含空刀夜提示）（D26/D27） | `test_agents_llm::TestWitchKnifeInfo` |
| S3 兜底吃解药 | 兜底动作改由插件 `neutral_action(step)` 给出（D25） | `test_actions_werewolf::TestNeutralAction`、`test_full_match_mock::TestFaultTolerance` |
| S4 重试链失效 | 可重试异常显式包含 openai SDK 异常，4xx 不重试（D27） | `test_cost::TestRetryChain` |
| S5 引擎耦合 | `StepContext` + `GameDefinition.play`，游戏流程移到 `flow.py`（D24） | `test_architecture`（engine 零游戏痕迹） |
| S6 动作零校验 | `validate_action(state, step, seat, action)` 真校验 + 存活座位白名单（D25） | `test_actions_werewolf::TestValidateAction` |
| M1 记忆层漏事件 | 记忆行渲染归插件 `memory_line`，补齐票型/警徽/开枪/上警/阶段标记（D26） | `test_memory_projection::TestMemoryCompleteness` |
| M2 放逐无 PK | `exile_resolve` 实现 PK（平票者发言 + 其余全体重投 + 再平票平安日） | `test_voting_flows::TestDayPk` |
| M3 发言定序缺失 | 新增 `speech_order` 步骤（警长定序 / rng 起始，落 `day.speech_order`） | `test_voting_flows::TestSpeechOrder` |
| M4 天数上限差一天 | 时限条件改为「第 `max_days` 天白天走完后」 | `test_full_match_mock::TestTimeLimit`、`test_rules_werewolf::TestWinner` |
| M5 死因外泄 | `night.resolved` 只带座位；死因另落 god 级 `night.death_cause` | `test_full_match_mock::test_死因只进god事件` |
| M6 费用恒为 0 | `compute_cost_micros` 按座位快照单价折算 | `test_cost::TestComputeCost/TestGatewayCostRecording` |
| M7 快照缺失 | `match_seat` 增 style/strategy/provider_id/单价（旧库幂等补列），runner 只用快照 | `test_seat_snapshot` |
| M8 座位号不校验 | 座位必须恰为 `1..N` 且不重复；未知 persona 422 | `test_api_validation::TestSeatValidation` |
| M9 API 契约不一致 | 实现 `provider_ref`、`Last-Event-ID` 头、`match.created`、404 语义；文档同步 | `test_api_validation::TestProviderRef/TestHttpContract` |
| M10 生命周期与 seq | runner 任务纳入 lifespan 统一中断并落 stopped；seq 改 DB 原子自增 + 唯一约束 | `test_api_validation::TestLifecycle`、`test_storage` |
| M11 安全 | 接入白名单（base_url 必须在 providers.json）、缺 key 422、CORS 白名单、可选 token | `test_api_validation::TestSecurity` |
| 轻微项 | 死因/幻影座位防护、`dialog._seat_str`、`filtered_view` 单点化、`phase.started` 的 day/phase、seed 语义、`apply_default_boards` 别名陷阱、关停未关仓储、TUI/前端阶段标签等 | 各自回归测试 + 全量 338 用例 |

**最终状态**：`backend` 全量测试 `350 passed`；前端 `vitest` 11 passed、`vue-tsc` 无错误。
仍待人工执行的验收：真实模型跑一局并对账费用面板（`scripts/e2e_real.py`）。

### 复核轮补充修复（D28）

修复完成后又跑了一轮独立对抗性复核（审查新代码 + 重跑本报告清单），追加修掉 5 条：

| 项 | 问题 | 修复 |
|---|---|---|
| 候选集 | 选举票可投给「从未上警者」并让其当选（候选集只进 prompt，不进校验） | `validate_action` 用 `step.params.candidates ∩ 存活` 作为合法目标集 |
| 提示词注入 | 他人发言可闭合 `</speech>` 并在记忆层伪造 `## 当前任务` 段落 | `fence_memory` 净化：尖括号/行首 `#` 转全角 |
| 重试链 | 坏 JSON 的**修复调用**遇网络错误直接抛出，外层重试失效 | 修复调用遇可重试错误回到外层循环 |
| 错误归因 | 插件 `validate_action` 抛异常被记成 `player.fallback`（谎报 LLM 故障） | 单独 try + 落 god 级 `plugin.error` |
| 迁移静默失败 | 旧库唯一索引补建失败被 `except: pass` 吞掉，seq 唯一性名存实亡 | 拆分 DDL 异常语义 + `duplicate_seq_groups()` 自检并 `log.error` |
| 关停泄漏 | （本轮自查发现）`_shutdown_runners` 在无在跑对局时不 close 两个 repository | 无论是否有对局都在 finally 中 close |
| 死亡链守门 | 放逐链只有「现在是否死亡」判定，对本就死亡的座位无效（D27 声称的迁移语义未落地） | 新增 `last_exile_was_alive`（投票前存活标记）守门 |
| 记忆层补全 | `day.speech_order` 等可见事件仍无落点 | 补 `day.speech_order`/`match.started`/`match.finished`；不落点的三类在文档写明理由 |
| 契约加固 | 插件缺 `neutral_action` 时引擎通用兜底对「用药」步并不中性 | 契约改为必须实现 + 引擎缺实现时告警一次 |

对应回归测试：`tests/test_adversarial_regressions.py`（12 例，含 PK 轮「投非候选者」端到端探针）+
`test_api_validation::TestLifecycle::test_空闲关停也要关闭仓储` + `test_actions_werewolf::TestApplySafety` 的迁移标记用例。
