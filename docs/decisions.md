# 决策记录

需求访谈与架构讨论收口的关键决策。格式：背景 → 决策 → 备选与否决理由 → 影响。新决策追加编号，旧条目不删改。

## D1 形态：AI 对战观赏台

- **背景**：产品形态要定：人机对战、纯 AI 观赏、还是混合。
- **决策**：纯 AI 对战观赏台，人只观看（实时追更 + 历史复盘），不入局、不操控。
- **备选**：人机混合对战——否决，v1 复杂度翻倍（要做人类输入通道、防窥屏隔离），且核心卖点是「看多模型互骗互演」。
- **影响**：无玩家输入通道；前端只有观赛/创建/历史三类页面。

## D2 规则分期：v1 最小流程局

- **背景**：狼人杀完整规则（预女猎白、警长、自爆、吞刀等）体量大。
- **决策**：v1 = 最小流程局（狼 + 预 + 民，6-10 人，固定流程）；标准完整局（预女猎白/警长等）后续做成**可自选档位**。
- **备选**：一次做全量规则——否决，首局验证周期不可控。
- **影响**：状态机只含 NIGHT_WOLF→NIGHT_SEER→DAWN→DAY_SPEECH→DAY_VOTE 循环；boards.json 预留 ruleset 档位字段。

## D3 板子：只配角色组合，技能写死

- **背景**：板子配置的自由度。
- **决策**：板子 = 角色组合预设（人数/狼数/神职数），技能行为写死在规则代码里；不做自定义角色、不做技能 DSL。
- **影响**：boards.json 只含 counts；validate_board 校验 6≤n≤10、狼 1~⌈n/3⌉、预 0~2、民≥1。

## D4 合作落点：狼队夜间私密频道

- **背景**：「多 AI **合作**对抗」的合作要在玩法上可见。
- **决策**：狼队夜间私密频道多轮商量定刀（ChannelMeeting）；收刀并行提案多数决。
- **影响**：channel.message 事件（可见性=频道成员）是观赛差异化卖点（上帝视角可见狼队互演）。

## D5 AI 玩家：每座位独立模型+人设，OpenAI 兼容

- **决策**：每座位独立配置模型 + 人设，多模型混战；统一 OpenAI 兼容接口，**不做 Claude 原生适配**。
- **影响**：llm/ 网关只实现 openai SDK 一种协议；providers 预设库按 OpenAI 兼容组织。

## D6 内心戏：结构化内心独白

- **决策**：每次发言同一次 LLM 调用附带产出结构化内心独白（monologue），god 视角可见，与公开言行对照出「言行不一」的节目效果。
- **影响**：输出 JSON 协议含 speech + monologue + action 三段；monologue 是独立事件（god 可见）。

## D7 复盘：历史列表 + 完整事件记录

- **决策**：历史列表 + 对局完整事件记录；**不做**时间轴拖拽/分叉重跑。但事件 append-only + 随机结果写入事件，为此类扩展留余地。
- **影响**：game_event 表 append-only；Reducer 架构（见 architecture.md 四支柱）。

## D8 视角：默认沉浸，一键上帝

- **决策**：默认沉浸视角（只看公开信息），一键切上帝全开；**过滤在服务端出站前统一做**，前端永远拿不到视角外数据。
- **影响**：每个事件带 vis_level/vis_seats；REST 与 SSE 共用同一过滤函数。

## D9 部署：本地单机 SQLite

- **决策**：本地单机 SQLite；Repository 抽象留后路（未来换 Postgres/上云）；无鉴权、无多房间。
- **影响**：storage/ 定义 Protocol + SQLite 实现。

## D10 座位级接入：每 agent 独立 base_url + api key

- **背景**：接入配置粒度。原计划为 provider 级共享 key；讨论后认为「同 base_url 多账号混战」「每 agent 完全独立端点」都是真实场景。
- **决策**：**座位级独立 key**：每个参赛 agent（座位）直接配置 `base_url + api_key_env + model`；providers.json 降级为**可选的接入预设库**（创建对局时展开固化）。key 本体仍只从环境变量解析，永不进配置/不落库。
- **备选**：provider 级共享 key——否决，账号池场景不支持；两级（provider 默认 + 座位覆盖）——否决，配置面与排查成本大。
- **影响**：match_seat 固化展开快照（base_url、api_key_env、model、单价），历史对局不依赖后续配置变更；详见 [agents-and-llm.md](agents-and-llm.md)。

## D11 人设拆分：style + strategy

- **背景**：策略 prompt 与人设风格混在一个 prompt 字段，难按维度调优。
- **决策**：personas.json 每条拆 `style`（语气/措辞/篇幅等表达风格）与 `strategy`（打法策略：出牌倾向、抗压方式、悍跳/倒钩偏好等）两个独立字段，prompt 拼装时分层注入。
- **备选**：合并单 prompt——否决（同上）；persona×game 策略矩阵（策略按游戏覆写）——否决，v1 过重，roadmap 留档。
- **影响**：prompt 六层拼装契约中 style/strategy 是独立两层；见 [agents-and-llm.md](agents-and-llm.md)。

## D12 rules 注入：按步骤切片

- **背景**：游戏规则文本注入粒度。
- **决策**：规则文本**按步骤切片**：每步只注入 overview 切片 + 当前步骤相关切片（夜聊带狼队规则、投票带计票规则）。
- **备选**：全量注入——否决，token 开销大且长规则稀释指令；全量 + 步骤强调——否决，token 最贵。
- **影响**：GameDefinition 契约新增 `rule_slices()` / `slices_for(step)`；游戏插件的规则文本按切片键组织；见 [game-plugin.md](game-plugin.md)。

## D13 文档与配置格式

- **背景**：设计文档要长期维护、随功能扩展；配置文件格式要统一。
- **决策**：设计文档全部放 `docs/` 并纳入 git 长期保留（按功能域拆分，见 [根 README](../README.md) 扩展约定）；**所有配置文件采用 JSON**（providers.json / personas.json / boards.json），加载校验仍走 pydantic，不引入 YAML 依赖；仓库根放简洁 `CLAUDE.md`，细节链接到 docs 子文档。
- **影响**：config/loader.py 用标准库 json 解析；文档与代码中的配置示例一律 JSON。

## D14 标准 12 人局 + v1 优化（对齐 whoisspy.ai 参考规则）

- **背景**：参考 whoisspy.ai「AI 狼人杀对抗赛」十二人局规则（见 [games/werewolf.md](games/werewolf.md) 来源对照），补全标准 12 人局并优化 v1 最小局。
- **决策**：
  1. 新增 ruleset `standard-12`：3 普通狼 + 狼王 / 预女猎守 + 4 民；含警长系统（上警/竞选/PK/归票/2 票/移交撕毁）、守卫悖论、死亡优先级结算矩阵、开枪（猎人/狼王，毒死不可）、胜负四条狼胜路径（屠边×2 + 屠城 + 第 8 天时限）、每晚猎人/狼王技能状态通知。
  2. v1（minimal）同步优化：发言上限 240 汉字截断；被投出者留遗言；白天平票改**平安日**（弃「带种子随机出局」）；定刀无合规目标改**空刀**（弃「随机合法目标」，引擎兜底同步改中性动作）；加天数上限 `max_days`（默认 8）。
  3. 比赛平台机制（评分/匹配/下线/接口形态）不吸收，进 roadmap。
- **备选**：照搬 perceive/interact 接口——否决，与 [agents-and-llm.md](agents-and-llm.md) 六层拼装 + JSON 协议冲突，只吸收规则语义。
- **影响**：GameDefinition 状态机支持竞选/PK/开枪/移交子流程（不新增 Step 原语，用 SoloAction/SerialSpeech/Ballot 编排，见 [game-plugin.md](game-plugin.md)）；事件类型新增守卫/女巫/开枪/警徽/技能通知（见 [events-storage.md](events-storage.md)）；rules 切片增至 10 键。※ 待确认 5 项见 [games/werewolf.md](games/werewolf.md) 文末。

## D15 标准 9 人局（ruleset standard-9）

- **背景**：在既有规则体系内补充更常见的 9 人局尺寸，让标准机制（警长/女巫/开枪/屠边）不锁死在 12 人。
- **决策**：新增 ruleset `standard-9`，固定组合 **3 狼 + 预言家 + 女巫 + 猎人 + 3 民**（无守卫、无狼王），板子 id `p9-standard`。复用 standard 全部机制与胜负规则（`check_winner` 与状态机均按 `ruleset.startswith("standard")` 分派）；守卫步由角色存活驱动自动跳过，不为板子写状态机分支。
- **备选**：为 9 人局开新 ruleset 分支实现（否决，机制重复）；放宽 standard-12 固定组合（否决，D14 的固定校验是防错设计，放宽会破坏既有测试语义）。
- **影响**：`rules.validate_board` 增 `standard-9` 分派与 `STANDARD9_ROLES` 常量；registry 增 `p9-standard` 预设；前端 `boardLabel` 统一 standard 标签；boards.json 样例与 [games/werewolf.md](games/werewolf.md) 板子表同步。

## D16 TUI 观看器与 SSE 续传/可见性出站语义（2026-09-23）

- **背景**：Web 前端之外需要终端「边跑边追更」的轻量入口（`--tui`）；实现终审发现三处契约缺口：SSE 断线续传游标（服务端读 `last_event_id` 查询参数、客户端只发 `Last-Event-ID` 头，游标传不进去；`events()` 无重试循环）；出站事件不带 `vis`、TUI 以 god 连流后客户端无依据做沉浸过滤（细化 [D8](#d8-视角默认沉浸一键上帝)）；座次表无数据源（缺 `role.dealt` 投影）。
- **决策**：
  1. 新增 TUI 子系统 `app/tui/`（SSE 客户端 + ViewModel 投影 + 纯函数渲染 + 主循环），入口 `python -m app.main --tui [--match-id N]`，与 Web 前端共用同一 REST/SSE 契约，不新增专属端点。
  2. SSE 断线续传游标统一为 **`last_event_id` 查询参数**（与前端 EventSource 重连一致）；TUI 客户端外层重试循环按 `_reconnect_delay` 指数退避重连，收到 `event: match_finished` 停止（保持对局结束 TUI 自然退出）。
  3. 出站事件统一附带 `vis {level, seats}`；TUI 始终以 `view=god` 连流，**沉浸过滤在客户端按 `vis.level` 做**（仅 public，与 `app/core.filtered_view` 语义一致），切视角不重连、不丢历史；`role.dealt`（seat 级）例外仍维护座次表，角色由渲染层按视角隐藏，不进对话流。
- **备选**：服务端改读 `Last-Event-ID` 头——否决，前端已按查询参数实现，双轨徒增不一致；视角切换时按 view 重连——否决，丢历史事件且需补拉重放；沉浸过滤只留服务端——否决，单条 god 连接无法响应客户端本地切视角。
- **影响**：`sse_client` 提供重试循环与游标 URL；`_event_dict` 增 `vis` 字段（前端忽略多余字段，向后兼容）；`apply_event` 增沉浸过滤与 `role.dealt`/死亡存活投影；[api.md](api.md) 同步续传与启动入口说明。

## D17 配置 JSON 化落地与真实 LLM 接入（2026-09-23）

- **背景**：D13 规定 providers/personas/boards 走 `backend/data/*.json`，但实现仍是 Python 硬编码（`config/defaults.py`、`registry.PRESETS`）；真实 LLM 接入存在关键缺口——API 层只把 `api_key_env` 变量名存进 seat_meta，从未解析成实际 key，导致非 mock 座位永远拿空 key 调不通。
- **决策**：
  1. 新增 `app/config/loader.py`：`load_config(data_dir)` 按文件加载 providers/personas/boards（pydantic 校验，坏文件抛 `ValueError` 拒绝启动），缺文件回落内置默认；boards 经 `apply_boards` 覆盖 `registry.PRESETS`。`.env` 解析手写（`parse_env_file`/`load_env_file`，不引入 python-dotenv），默认文件 `app/config/.env`，启动时注入 `os.environ`（不覆盖已有变量）。
  2. **key 解析边界**：`resolve_api_key(api_key_env)` 只在 `_spawn_runner` 处把变量名解析成 key 进内存 seat_meta；落库 match_seat 仍只有变量名，catalog/providers 响应连 `api_key_env` 字段名也脱敏。
  3. 真实跑局双入口：`scripts/e2e_real.py`（CLI，读配置选首个非 mock provider，p6-classic 起）与 TUI `--real` 开关（自动开局用真实 provider）；共享 `app/scripts_helpers/e2e.py` 的 `pick_provider`/`build_real_seats`，key 变量未设置时直接报错而非静默走兜底。
- **备选**：引入 python-dotenv——否决，20 行解析足够，少一个依赖；key 存配置文件——否决，违反全局安全规范；key 解析下沉进 gateway——否决，gateway 保持"拿什么调什么"的纯接入层，变量名→key 的换算属于 API 层装配职责。
- **影响**：`create_app(db_path, data_dir)` 启动时加载配置（catalog 接口改用 bundle）；`e2e_real.py` 补齐 [run_match.py](../backend/scripts/run_match.py) 提示却不存在的真实入口；`--tui --real` 组合可边看真实局边复盘；[configuration.md](configuration.md) 补 `.env` 加载说明。

## D18 persona 绑定接入：选手卡 = 性格 + 模型（2026-09-24）

- **背景**：此前座位接入只能逐座位显式给 base_url/api_key_env/model，或全桌统一走 e2e 的默认 provider；「让不同模型同台竞技、每个选手固定用某个模型」需要每次手工拼座位表。用户在 providers.json 增加 mimo-v2.6-pro 子模型后提出按 persona 选择子模型。
- **决策**：persona 增加可选 `provider_id` + `model` 字段（绑定即「选手卡」）：
  1. 加载时交叉校验：`provider_id` 必须存在于 providers.json、`model` 必须属于该 provider、只给 model 不给 provider_id 直接拒绝启动（`_validate_persona_bindings`）。
  2. API 创建对局：座位未显式指定接入（`SeatIn.model` 默认改空串 = 未指定）时按 persona 绑定展开 base_url/api_key_env/model；显式指定优先于绑定；都没有 → mock。key 解析路径不变（仍只在 `_spawn_runner` 进内存）。
  3. `build_real_seats` 增加 `personas`/`providers` 参数：e2e_real.py 与 TUI `--real` 按 personas.json 顺序循环取用座位，绑定涉及的所有 key 变量缺失即报错。
- **备选**：把 provider 段内嵌进 personas.json——否决，providers 是接入事实、personas 是选手配置，合并后两处引用同一 provider 会重复；座位绑定写进 match_seat 落库新字段——否决，展开仍发生在 API 层，落库结构不变（D10 展开固化语义已覆盖）。
- **影响**：`SeatIn.model` 默认值从 "mock" 改为 ""（请求体显式传 "mock" 不受影响，向后兼容）；loader 校验失败含 persona id 便于定位；[configuration.md](configuration.md) 补绑定示例与优先级说明；全场同一模型的「队内赛」与多模型混搭「对抗赛」都只改 personas.json 即可。

## D19 未绑定座位池内随机分配模型 + 分配留痕（2026-09-24）

- **背景**：D18 后未绑定 persona 的座位在真实跑局入口全部落到「provider 首个模型」，多模型池（mimo flash/pro）形同虚设；用户要求「随机分配 model，做好分配后的记录」。
- **决策**：
  1. **分配规则**（优先级）：座位显式指定 > persona 绑定 > 池内随机（真实跑局入口）> mock（API 未指定默认）。随机用 `Random(对局 seed)`，同 seed 可复现；`--model` 收窄池为单模型（显式覆盖优先于全池随机）。
  2. **留痕双写**：每座位最终模型随 `match_seat` 落库（D10 展开固化，天然权威）；完整分配记录 `board.model_assignments = [{seat, persona_id, model, basis, provider_id}]` 随 board JSON 落库（API 创建时透传、e2e/TUI 开局写入），`basis` 区分 `persona_binding`/`random`。开局时打印「模型分配」清单。
- **备选**：只靠 match_seat 记录——否决，无 `basis` 无法区分绑定与随机、复盘看不出「谁被分到什么、为什么」；分配写独立事件表——否决，board JSON 已是现成的对局元数据载体，不加表。API 默认也随机——否决，POST /api/matches 默认必须零成本 mock（隐式产生真实调用会意外花钱）。
- **影响**：`build_real_seats` 返回 `(seats, assignments)`；`assignment_pool_for(provider, model_id)` 提供 CLI 池收窄；[configuration.md](configuration.md) 优先级与留痕说明同步。

## D20 警长竞选时机复位：死讯公布前 （2026-09-24）

- **背景**：D20 当日把警长竞选从夜末移到白天发言后（引擎 + 测试 + 文档一并改），实施后用户明确拍板「警长竞选在公布死讯前」，要求全部文件按该规则统一。复核还发现 D20 实现存在重复缺陷：`sheriff_elect → night_resolve → day_speech` 分支残留，竞选后死讯公布与白天发言会各执行两遍。
- **决策**：回到 D14 原始顺序（同时也是参考规则待确认项的暂定方向）——**夜末竞选 → night_resolve 公布死讯 → 白天发言 → 放逐投票**：
  1. `_after_night` 恢复竞选分支（standard、day==1、未 `elect_done` 时先 `sheriff_elect`），竞选完成后走 `night_resolve`。
  2. `next_step` 的 `day_speech` 分支不再插入竞选，直接进 `day_vote`（消除重复死讯/发言缺陷）。
  3. `test_sheriff_flow.py` 重写为 3 用例：竞选在 `night_resolve` 前、夜末位于 `witch_turn` 后、投票前死讯与发言各仅一次。
  4. [games/werewolf.md](games/werewolf.md)：竞选小节移至白天流程之前（标注夜末、死讯前）；状态机图竞选步骤移到 DAWN 前；待确认项 5 标记已确认。
- **备选**：保持 D20（发言后竞选）——否决，用户拍板回滚且该实现有重复执行缺陷；竞选放在死讯后、发言前——否决，用户明确要求死讯前。
- **影响**：D20 被本条推翻（条目保留作历史）；引擎/测试/文档三方与「竞选在死讯前」对齐；standard-9/standard-12 共用同一时序（`state.extra["standard"]` 驱动）。

## D21 规则切片按步骤注入 + 前缀缓存可观测（2026-09-24）

- **背景**：审查 prompt 结构时发现两处问题。其一，`MatchRunner._ask` 取规则切片传的是占位 `Step(kind="")`，`slices_for` 对空 kind 只返回 `["overview"]`——D12「按步骤注入角色规则」从未生效，模型全程只见过 overview，狼队频道/预言家/女巫/守卫等切片一次都没进过 prompt。其二，前缀缓存命中率完全无法观测：`llm_call` 只记 prompt/completion 总量，不区分缓存命中，`cost_micros` 因此高估，「结构是否吃满前缀缓存」无从验证。修复其一会引入新风险：本步切片若照原第 1 层位置注入，随步骤切换变化会作废整段记忆前缀。
- **决策**：
  1. **计量先行**：`parse_usage_tokens` 归一各家端点 usage（OpenAI 系 `prompt_tokens_details.cached_tokens`、DeepSeek 系 `prompt_cache_hit_tokens`，对象/dict 形态皆认），`llm_call` 增列 `cached_prompt_tokens`，`summarize` 输出 `cached_prompt_tokens` + `cache_hit_rate`（total 与 by_model 两级）。旧库由 `SqliteUsageRepository.init` 幂等补列（`_MIGRATE_COLUMNS` 固定 DDL，独立事务吞 duplicate column）。
  2. **`_ask` 显式收 `step`**：`purpose` 与 `Step.kind` 不可互推（ballot 的 purpose 是 "vote"、solo_action 是 "action"、serial_speech 是 "speech"/"sheriff_speech"），故 12 个调用点各自传真实 `Step`；`_speech_round` 同步透传。
  3. **层序按缓存语义重排**：`_rule_partition(step)` 以 `slices_for(空 step)` 为基线切出稳定段，其余归本步易变段；`build_user_prompt` 新增 `step_slices`，把本步切片从第 1 层挪进第 6 层（指令层）。契约变为「稳定段（全局规则/身份/人设/策略）→ 追加式记忆 → 易变段（本步切片 + 指令）」，并写入 [agents-and-llm.md](agents-and-llm.md) 作为红线（记忆层必须 append-only，禁止状态表/回填）。
- **备选**：按 purpose 推导 step kind——否决，与 `Step.kind` 不同名且无法一一映射；全量规则切片一次性塞进第 1 层——否决，浪费 token 且违背 D12 的按步切片意图（稳定前缀只需够长越过端点最小缓存门槛）；改 `GameDefinition.slices_for` 契约返回 (稳定, 易变)——否决，缓存分层是 prompt 组装职责，不该泄漏进游戏插件契约；只记 token 总量不做缓存区分——否决，成本失真且优化无据可依。
- **影响**：D12 真正生效（每步注入对应规则切片）；`GET /api/matches/{id}/usage` 多出 `cached_prompt_tokens`/`cache_hit_rate`，可实测 prompt 结构的缓存收益；`build_user_prompt` 增可选参数 `step_slices`（缺省不注入，向后兼容）；[api.md](api.md)、[events-storage.md](events-storage.md) 同步。

## D22 输出 schema 字段顺序：monologue 先于 speech（2026-09-24）

- **背景**：D6 确定 monologue 与 speech 同一次调用产出（言行对照是节目效果核心），但 schema 里 `speech` 排在 `monologue` 之前。JSON 字段顺序即自回归模型的生成顺序，于是模型**先写公开发言、再写内心独白**，独白容易沦为对发言的事后合理化；叠加模型的自我一致性倾向，「表里不一」这个核心卖点会被写自洽而抹平。
- **决策**：输出 JSON 协议字段顺序改为 `monologue` → `speech` → `action`，并同步所有示范协议的位置：`build_user_prompt` 指令层 schema、`parse_agent_response` 的容错格式修复提示、`MockLLM._heuristic_reply` 返回、测试与文档中的协议样例。新增 `TestOutputSchemaOrder` 锁死该顺序（断言 schema 片段内 `'"monologue"'` 先于 `'"speech"'`）。
- **备选**：拆成两次独立调用分别产独白与发言——否决，成本与延迟翻倍且第二跳无法共享前缀缓存，而单次调用 + 顺序调整已能拿到主要收益；只改文案强调「先想后说」而不调字段顺序——否决，文案约束弱于生成顺序约束；保持 speech 在前——否决，与 D6 的言行对照目标相悖。
- **影响**：仍是单次调用输出三段（不变），不改 `parse_agent_response` 的 key 寻址解析（顺序无关，向后兼容历史响应）；[agents-and-llm.md](agents-and-llm.md) 协议小节同步。

## D23 单板收敛：只保留 standard-9（2026-09-24）

- **背景**：后端一次审查（[reviews/backend-audit-2026-09-24.md](reviews/backend-audit-2026-09-24.md)）发现标准局核心机制存在真实缺陷（当选警长被选举票判死、警长平票 PK 崩溃、守卫/狼王/极简局各有独立分支），而每多一块板子/一套 ruleset，就多一条需要维护与测试的路径。用户明确要求「删掉除标准 9 人局以外的任何其他配置，以减小出错可能」。
- **决策**：
  1. **只保留 ruleset `standard-9` 与板子 `p9-standard`**（3 狼 + 预言家 + 女巫 + 猎人 + 3 民）：删除 `minimal`、`standard-12`、守卫、狼王相关代码、预设、测试与文档。
  2. `validate_board` 只认固定组合（任何其他 roles/ruleset 一律 `ValueError` → API 422）；`resolve_board` 对未知板子 id 直接拒绝（不再静默回落默认板子）。
  3. 默认板子 id 统一走 `registry.DEFAULT_BOARD_ID`（API 默认值、`--board` 默认值、脚本默认值同源）。
  4. 附带修复 `loader.apply_default_boards` 的别名陷阱：`DEFAULT_PRESETS` 改为注册表 `PRESETS` 的快照拷贝，否则 `apply_boards` 清空的是同一个 dict，内置默认再也恢复不回来。
- **备选**：保留多板子只修缺陷——否决，用户要求收敛且多路径正是缺陷温床；保留 minimal 代码但不出预设——否决，会成为无人验证的休眠路径；把守卫/狼王做成可选角色——否决，standard-9 的规则文本与结算矩阵里没有它们。
- **影响**：`rules.py` 只剩一套纯函数；`definition.py`/`flow.py` 去掉 `standard` 分支与守卫步；[games/werewolf.md](games/werewolf.md) 重写为单板文档；测试与脚本全面改到 `p9-standard`（9 座）。

## D24 引擎与游戏插件解耦：StepContext + play/flow（2026-09-24）

- **背景**：审查发现 `engine/runner.py` 直接 `import app.games.werewolf.rules`，并硬编码角色名（seer/witch/hunter/wolf）、游戏私有状态键（`extra["sheriff"]`/`used_save`/`night`）、11 个狼人杀专属 step kind 与中文业务串（`title.startswith("放逐")`）——`docs/game-plugin.md` 与 `CLAUDE.md` 规则 6 声称的「engine 不为具体游戏改动」实际已被打破，接第二个游戏必须改引擎。
- **决策**：
  1. 引擎新增 **`StepContext`**（实现 `engine/context.py`）：只暴露 IO 原语 `emit / ask（可带子步骤）/ ask_many / speech / collect_ballot / monologue` 与只读的 `state/spec/rng/step`。
  2. 插件新增 **`GameDefinition.play(ctx, step)`**：每一步问谁、怎么结算、写哪些事件，全部写在 `games/werewolf/flow.py`（handler 表按 step kind 分派）；`runner._exec_step` 缩减为「构造 ctx + 调用 play」。
  3. 计票/定刀/夜间结算仍留在插件（`rules.py` 纯函数），引擎不再 import 任何具体游戏模块。
  4. 新增 `tests/test_architecture.py` 锁死边界：engine 目录下不得出现 `werewolf`/角色名/游戏事件名；插件不得 import `engine.runner`/`engine.context` 实现。
- **备选**：把「结算钩子」做成少量方法（`resolve_night`/`tally` 等）注入引擎——否决，钩子数量会随游戏变多而膨胀，且状态机分支仍留在引擎；保留现状只更新文档——否决，等于承认插件契约失效。
- **影响**：`runner.py` 从约 700 行降到约 270 行且零游戏痕迹；`games/werewolf/flow.py` 承载全部步内流程；`game-plugin.md` 的「4 原语」章节改写为 StepContext 契约；`tests/test_engine.py` 的假游戏实现自己的 `play`，成为契约可替换性的活证据。

## D25 动作合法性/兜底归插件 + 座位接入白名单（2026-09-24）

- **背景**：两处安全与正确性缺口。其一，`validate_action(state, seat, action)` 是空实现（只做类型归一），幻觉目标可以入票、放逐已死玩家、给不存在的座位发遗言，甚至让已死猎人二次开枪；容错兜底又用「请求类型 + target 0」的通用动作，导致女巫超时后**用掉了解药**（甚至触发守卫悖论）。其二，API 允许座位自带任意 `base_url` + `api_key_env`，配合 `CORS *` 与无鉴权，「用户浏览器里的任意网页」可以诱导后端把真实 key 发到攻击者地址，或直接拉走上帝视角数据。
- **决策**：
  1. **动作权威归插件**：契约改为 `validate_action(state, step, seat, action)`——按 `step.kind` 判定允许的动作类型集合，target 必须是存活座位，女巫用药受药数与刀口约束（空刀夜不能用解药）；任何非法输入降级为 `neutral_action(state, step)`。
  2. **中性兜底归插件**：`neutral_action` 按步骤给出真正中性的动作（女巫步 → `pass`），引擎只在插件未实现时回落通用兜底；`ctx.ask/ask_many/speech/collect_ballot` 支持显式子步骤（竞选报名/收刀/开枪/警徽各有自己的 kind），避免「用外层 step 校验子步骤动作」的错配。
  3. **座位接入白名单**：显式 `base_url` 必须与 providers.json 中某条一致（否则 422）；真实接入必须能解析到非空 key（否则 422，不再静默跑出全兜底假局）；新增 `provider_ref` 写法（`provider_id` 或 `provider_id/model_id`）作为推荐入口。
  4. **入口收紧**：CORS 从 `*` 改为来源白名单（`WHOISSPY_CORS_ORIGINS` 可覆盖）；新增可选 `WHOISSPY_API_TOKEN`（设置后所有请求需带 `X-API-Token` / `Authorization: Bearer`）；`stop`/`usage` 对不存在的对局返回 404。
- **备选**：把校验写在引擎的候选集比对里——否决，候选集语义随游戏变化，只有插件知道；保留 `CORS *` 只加 token——否决，token 默认关闭时等于没防线，浏览器侧仍可直连；禁止一切自定义 base_url——否决，座位级独立 key（D10）是真实需求，白名单已能挡住外带。
- **影响**：`definition.py` 增加 `_STEP_ACTIONS`/`_NEUTRAL_ACTIONS` 两张表与真实校验；`api/app.py` 增加接入解析与校验、CORS/令牌中间件；[configuration.md](configuration.md)、[api.md](api.md) 同步安全约束。

## D26 记忆层与阶段天数归插件（2026-09-24）

- **背景**：审查实测标准 12 人局整局后，某座位**可见但被记忆层静默丢弃**的事件包括 `vote.cast`（43 次）、`sheriff.badge`（7 次）、`gun.shoot`（2 次）、`sheriff.registered`——模型因此看不到票型、不知道谁是警长、不知道有人被枪杀，「盘票型」策略（人设里明写）无法执行。同时 `phase.started` 的 `day_index/phase` 用的是上一步的值（夜首记成前一天），导出分段错位。
- **决策**：
  1. 记忆行渲染改为插件契约 **`GameDefinition.memory_line(event)`**：凡本座可见的事件都必须有落点（含票型/警徽/开枪/上警名单/阶段标记），engine 只负责按 `VisMeta` 过滤可见性。
  2. 阶段天数改为插件契约 **`phase_day(state, step)`**：`phase.started` 的 `day_index` 与 `payload.day` 由插件给出（狼人杀在入夜时推进天数），不再差一天。
  3. 防注入声明从记忆层挪到**指令层**（`docs/agents-and-llm.md` 原本就要求如此）。
- **备选**：继续在引擎里维护事件白名单——否决，那正是 D24 要消除的耦合；把记忆层改成状态快照（存活表/票数汇总）——否决，违反 append-only 红线且作废前缀缓存。
- **影响**：`runner._memory_line` 变为插件委托；`definition.memory_line` 覆盖 11 类事件；`test_memory_projection.py` 全面改写并新增完整性回归用例。

## D27 事件语义与生命周期修正（2026-09-24）

- **背景**：审查发现一批「文档承诺 vs 实现」的语义缺口：手动终止的对局被写成「狼人胜利 + finished」（`elif stop` 是死分支）；死因随 public 的 `night.resolved` 外泄；放逐平票没有 PK；白天发言固定升序（无警长定序、无 rng 起点）；`max_days` 早生效一整天；`cost_micros` 恒为 0；`match_seat` 没有 style/strategy/单价快照；`seq` 由进程内锁分配且无唯一约束；runner 任务不受生命周期管理。
- **决策**：
  1. **终止语义**：`match.finished` 只在真正分出胜负时发出；手动终止/步数超限/状态机停摆一律 `match.stopped`（带 reason）+ `status=stopped` + `result.winner=null`；runner 任务纳入 API 的注册表，lifespan 关停时统一中断并落 stopped，不留 running 僵尸。
  2. **事件语义**：新增 `match.created`（首条）、`night.started`（入夜清空收集，事件驱动）、`night.death_cause`（死因，god）、`day.speech_order`（发言顺序，public）；`night.resolved` 只带死亡座位不带死因；`vote.resolved` 增 `scope`（exile/sheriff）且只有 `exile` 才判死（修复「当选警长被判死」）；删掉按中文标题嗅探的 `_last_exile` 逻辑。
  3. **流程补齐**：放逐平票走 PK（平票者发言 + 其余全体重投，仍平票平安日）；白天发言定序（有警长由警长指定首位，否则 rng 随机，按座位升序环绕）；技能状态通知移到夜序末尾并按死因给 `can_shoot`；时限判定改为「第 `max_days` 天白天走完后」。
  4. **计量与快照**：`compute_cost_micros` 按座位快照单价折算真实费用（未命中输入价 + 命中缓存价 + 输出价）；`match_seat` 增 style/strategy/provider_id/三个单价字段（旧库幂等补列），runner 一律用快照，历史对局可复现；`game_event` 增 `UNIQUE(match_id, seq)`，seq 改由 DB 原子自增（`UPDATE … RETURNING`）分配。
  5. **重试链修正**：可重试异常显式包含 openai SDK 的 `APIConnectionError/APITimeoutError/RateLimitError/InternalServerError`（它们不继承内置 `ConnectionError/TimeoutError`），4xx 不重试。
- **备选**：保留 `winner="wolf"` 表示终止——否决，类型上无法表达「无胜者」，历史列表会显示假胜利；死因留在 public payload 由前端隐藏——否决，服务端过滤是唯一防线（支柱 3）；seq 只加唯一约束不加原子自增——否决，冲突会变成写失败而非自愈。
- **影响**：`runner.run` 收尾分支重写；`definition.apply` 按 `scope` 归约并记录放逐结果；`flow.py` 补齐 PK/定序/结算链；`storage` 增列/增索引/改 seq 分配；`gateway` 增费用折算与重试类型；测试新增 `test_voting_flows`/`test_cost`/`test_api_validation`/`test_seat_snapshot` 等回归。

## D28 对抗性复核后的加固（2026-09-24）

- **背景**：D23–D27 落地后又跑了一轮独立对抗性复核（一次审查新代码、一次重跑原始缺陷清单），
  报出 5 条仍需处理的问题：选举票可投「从未上警者」（候选集只进 prompt 不进校验）、
  他人发言可闭合 `</speech>` 并在记忆层伪造 `## 当前任务` 段落、坏 JSON 修复调用失败时外层重试失效、
  插件 `validate_action` 抛异常被计成「LLM 调用失败」、旧库唯一索引补建失败被静默吞掉。
- **决策**：
  1. **候选集进校验**：`validate_action` 取 `step.params.candidates ∩ 存活` 作为合法目标集
     （警长选举只能投上警者、PK 只能投平票者、验人/开枪/毒药同理），0 仍表示弃权。
  2. **围栏净化**：`fence_memory` 把发言内容里的 `<`/`>` 转全角、行首 `#` 转全角——
     围栏不可被内容闭合，也无法伪造 prompt 段落（视觉几乎无差别）。
  3. **重试语义**：坏 JSON 每个原始响应只做一次格式修复；**修复调用本身**撞上网络/超时/5xx 时回到外层重试。
  4. **插件错误单独记账**：`validate_action`/`neutral_action` 的异常不再落 `player.fallback`，
     改落 god 级 `plugin.error`（含 step 与原因），动作回落通用中性动作——插件 bug 不再冒充「LLM 调用失败」。
  5. **迁移可诊断**：旧库 DDL 拆成「补列（可吞）」与「建唯一索引（失败必须 `log.error`）」，
     并提供 `duplicate_seq_groups()` 启动自检，暴露重复 `(match_id, seq)` 以便清理。
  6. **死亡链守门**：放逐链新增 `last_exile_was_alive`（投票前存活标记），
     只有「本轮真的从存活变死亡」的座位才走遗言/开枪链（原先的「现在是不是死的」判定对本就死亡的座位无效）。
  7. **记忆层补全**：`day.speech_order` / `match.started` / `match.finished` 也进记忆；
     `role.dealt` / `night.started` / `match.created` 刻意不落点（信息已由身份层与阶段标记给出），并在文档里写明理由。
- **备选**：把候选集校验留在引擎侧（否决，引擎不认识候选语义）；围栏改用引用前缀+缩进（否决，
  改动大且伤可读性，转义已足够）；插件异常直接让对局失败（否决，违背「绝不卡死整局」容错链）。
- **影响**：`definition.validate_action` 增候选集分支；`protocol.fence_memory` 增 `_sanitize_speech`；
  `gateway.ask_json` 修复分支增可重试兜底；`runner._ask` 拆出插件错误路径；`storage/repo.py` 增迁移诊断；
  新增 `tests/test_adversarial_regressions.py` 锁死这 5 条。
