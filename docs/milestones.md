# 里程碑与测试策略

TDD 为铁律：先写失败测试，看它失败，再写最小实现转绿（Red-Green-Refactor）。配置文件豁免。

## M1 引擎骨架 + 无 UI 跑通

顺序：脚手架（配置豁免）→ TDD `games/werewolf/rules.py`（发牌/计票/胜负/刀验结算纯函数）→ TDD `storage/`（append-only 事件表、seq、可见性元数据、llm_calls）→ TDD `agents/protocol.py` + `llm/gateway.py`（解析修复链、重试计量、MockLLM）→ TDD `engine/`（4 原语、狼队频道、容错、MatchRunner）→ `scripts/run_match.py --mock` 端到端。

**验收**：

- [ ] `--mock` 确定性跑完整局；事件 seq 连续；可见性断言正确。
- [ ] 规则单测全绿：三种终局、平票同种子可复现、发牌边界拒绝。
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

## 测试策略

| 层 | 内容 |
|---|---|
| 单元 | rules.py 纯函数（胜负边界 1狼1民=狼胜、计票平票、刀验结算、发牌校验）；`apply` 重放 ≡ 直接构造 |
| 可见性 | 沉浸/上帝过滤矩阵测试锁死（响应体零泄漏） |
| 集成 | MockLLM 完整局 10 种子 × 3 板子 <10s 全绿；故障注入（30% 坏 JSON + 超时）不卡死；API/SSE 补发、Last-Event-ID、view 过滤 |
| 前端 | Vitest：project.ts 投影、store 去重/gap 补拉 |
| e2e 手动 | `scripts/e2e_real.py` 便宜真实模型跑 6 人局冒烟，记录 JSON 遵从率与费用 |
