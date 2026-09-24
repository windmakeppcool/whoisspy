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
