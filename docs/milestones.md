# 里程碑与测试策略

TDD 为铁律：先写失败测试，看它失败，再写最小实现转绿（Red-Green-Refactor）。配置文件豁免。

## M1 引擎骨架 + 无 UI 跑通

顺序：脚手架（配置豁免）→ TDD `games/werewolf/rules.py`（发牌/计票/胜负/刀验结算纯函数）→ TDD `storage/`（append-only 事件表、seq、可见性元数据、llm_calls）→ TDD `agents/protocol.py` + `llm/gateway.py`（解析修复链、重试计量、MockLLM）→ TDD `engine/`（4 原语、狼队频道、容错、MatchRunner）→ `scripts/run_match.py --mock` 端到端。

**验收**：

- [ ] `--mock` 确定性跑完整局；事件 seq 连续；可见性断言正确。
- [ ] 规则单测全绿：胜负边界（1狼1民=狼胜、屠边、第 8 天时限）、定刀平票同种子可复现、发牌边界拒绝、夜死结算矩阵（同守同救死/毒不被挡）。
- [ ] 真实 API 跑一局，费用与 llm_call 汇总一致。
- [ ] 故障注入（坏 JSON/超时）仍跑完整局并产生 `player.fallback`。

## M2 SSE + 观赛 UI + 历史

创建表单先硬编码座位配置；MatchListView / CreateMatchView / MatchView + MatchStage 全组件。

**验收**：

- [ ] 浏览器增量追更有序。
- [ ] 断线重连无丢失无重复（Last-Event-ID 补发 + 前端 seq 去重/补拉）。
- [ ] 历史详情与观赛逐事件一致（同一 MatchStage）。
- [ ] 沉浸视角网络响应体无任何 god/seat 数据；切上帝全亮。

## M3 多模型 + 人设 + 内心独白 + 用量 + 板子配置

**验收**：

- [ ] 6 座不同 persona、≥2 种 model 混战跑通，风格可感知。
- [ ] 上帝视角每条发言可对照独白。
- [ ] UsagePanel 与 llm_call 一致。
- [ ] 改 boards.json 重启可选新板子。
- [ ] 全库 grep 无 key 明文。

## M4 单板收敛 + 审查缺陷修复（2026-09-24）

背景：后端审查（[reviews/backend-audit-2026-09-24.md](reviews/backend-audit-2026-09-24.md)）报了 8 条严重 + 11 条中等问题。
用户决策：**先收敛配置面，再全量修复**（D23–D27）。

范围：

- 板子收敛为唯一 `p9-standard`（删除 minimal / standard-12 / 守卫 / 狼王）。
- 对局正确性：警长选举票不再判死、警长平票 PK 不崩、放逐平票走 PK、发言定序、天数上限口径、死因不外泄。
- 容错与计量：插件级中性兜底（女巫不会白耗解药）、openai 异常重试、按单价折算真实费用。
- 契约与安全：动作校验归插件、座位接入白名单、CORS 白名单、可选 token、`provider_ref`、`Last-Event-ID` 头。
- 结构：引擎与游戏插件解耦（StepContext + play/flow），`tests/test_architecture.py` 锁死边界。

**验收**：

- [x] 全量测试全绿（`pytest -q` 350 例，含新增的 7 个专项回归文件）。
- [x] `tests/test_architecture.py`：engine 目录不含任何具体游戏痕迹；插件不反向依赖引擎内部。
- [x] 实测：警长当选后继续投票；警长首轮平票走 PK 不抛异常；放逐平票走 PK；第 N 天白天走完才判时限。
- [x] 实测：调用全部失败时女巫不消耗解药；openai SDK 异常会重试、4xx 不重试；费用非零。
- [x] 实测：座位号重复/越界 422；未知 persona/provider/板子 422；裸 base_url 422；缺 key 422。
- [x] 实测：关停时在跑对局落 stopped 且无悬挂 task；空闲关停也关闭仓储；`game_event` seq 唯一。
- [x] 对抗性复核（新代码审查 + 原缺陷清单复跑）发现的 5 条追加问题已修（D28）。
- [ ] 真实模型跑一局：JSON 遵从率与费用面板对账（待人工执行 `scripts/e2e_real.py`）。

## 测试策略

| 层 | 内容 |
|---|---|
| 单元 | rules.py 纯函数（板子校验、计票/平票、定刀、夜间结算矩阵、胜负边界）；`apply` 重放 ≡ 直接构造 |
| 契约 | `test_actions_werewolf`（动作校验/中性兜底）、`test_architecture`（引擎与插件边界）、`test_memory_projection`（记忆完整性） |
| 可见性 | 沉浸/上帝过滤矩阵测试锁死（响应体零泄漏） |
| 集成 | MockLLM 完整局（多 seed 确定性）；`test_voting_flows`（PK/定序）、`test_full_match_mock`（机制闭环/时限/兜底） |
| API/安全 | `test_api_validation`（座位校验/provider_ref/CORS/token/生命周期/游标）、`test_seat_snapshot`（快照可复现） |
| 计量 | `test_cost`（费用折算、重试链覆盖 openai 异常） |
| 前端 | Vitest：project.ts 投影、store 去重/gap 补拉 |
| e2e 手动 | `scripts/e2e_real.py` 便宜真实模型跑一局冒烟（9 人 standard-9），记录 JSON 遵从率与费用 |
