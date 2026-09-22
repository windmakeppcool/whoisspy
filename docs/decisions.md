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
