# 13 测试策略（TDD）

铁律不变：**先写失败测试再写实现**（配置文件豁免）。测试与模块一一对应，
纯函数模块（rules/state/memory/present/prompts）的测试不需要任何夹具。

## 一、测试文件与覆盖点

| 文件 | 覆盖点 |
|---|---|
| `test_rules.py` | 发牌组合与同 seed 复现；定刀（多数/平票 rng/全员弃权空刀/无狼）；计票（警长 2 票/平票/全弃权）；夜结算矩阵**全分支**（含同刀同毒两态）；胜负（屠边×2/屠城/时限不提前）；validate_action（非法 type/target 越界降级、女巫三态、register 布尔化）；neutral_action 全 phase |
| `test_state.py` | 逐事件 apply 语义；**折叠一致性**：手造事件序列 fold ≡ 现场状态；判死防御（幻觉座位/None/已死）；last_exile_was_alive 取样时机 |
| `test_memory.py` | 每类事件记忆行；围栏净化（尖括号/行首 #）；刻意不落点清单；label 取自事件 payload |
| `test_present.py` | 每类事件观赛行；god/public 视角过滤；role.dealt 只在 god 上屏 |
| `test_prompts.py` | 六层顺序；本步切片只进第 6 层；prompt_extra 落指令层；合法目标列表渲染 |
| `test_agent.py` | JSON 解析链（好/坏/修复成功/修复失败兜底）；三层失败三种记账（fallback/rule.error/静默降级）；240 截断 |
| `test_llm.py` | mock 确定性（同 prompt 同回复、公式锁死）；重试语义（openai 异常族、退避次数、4xx 不重试）；usage 归一（OpenAI/DeepSeek 两种形态）；cost 计算（含 cached>prompt 防死负）；trace 落盘 schema |
| `test_store.py` | DDL 幂等；seq 唯一约束生效；append-only 读回等价；座位快照落库；用量汇总 |
| `test_flow_night.py` | 狼聊轮次与串行记忆；空刀全链；无预言家/女巫跳过；猎人通知（被毒不能开枪）；死亡链（开枪/移徽/被枪杀者不连锁） |
| `test_flow_day.py` | 警长选举全分支（无人/恰一/全员/首轮平票 PK/再平票丢徽）；定序（警长指定/无警长 rng/非法目标回落）；放逐平票 PK 与平安日；遗言；警长被放逐移徽 |
| `test_flow_e2e.py` | mock 全局跑通多局（不同 seed 分别覆盖狼胜/好人胜）；**同 seed 两次运行事件 JSON 逐字节一致**（P3 验收）；护栏（假网关无限失败 → max_calls stopped） |
| `test_export.py` | schema 完整性；view 过滤；分段（开局/夜/昼、警长竞选归当夜）；usage 块（fallbacks 计数） |
| `test_cli.py` | 参数解析；mock 冒烟（进程内调用）；预检失败退出码 3 |

## 二、flow 测试的注入方式

不引入接口抽象：`MatchRun.gateway` 传假的 `complete`（普通 async 函数，按 prompt
反解座位与动作类型返回预设回复），或直接用内置 mock provider + 特定 seed。
旧体系里 FakeGame/spy 网关那套一次性脚手架不再需要——纯函数 + 平铺模块让夹具降到最少。

## 三、验收基线（全部绿才算重写完成）

1. `test_flow_e2e` 的确定性用例：同 seed 两次全流程运行，事件序列 JSON 完全一致；
2. 夜结算矩阵、警长选举、放逐 PK 每个分支至少一个直接用例（分支表见 02/05）;
3. mock 全量跑一局耗时 < 5s（无网络依赖）；
4. `--real` 冒烟（有 key 环境）跑完一局且用量/费用汇总非零——无 key 环境标记 skip。
