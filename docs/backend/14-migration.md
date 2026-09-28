# 14 删除与落地记录（migration）

> **✅ 已执行完成（2026-09-25）**：本节全部步骤已按序落地并推送（`main` 分支）。
> 落地过程中的实际偏差与防御性修复见文末「执行记录」；前端处置仍生效（暂不可用）。

> 本文档批准后执行。此前**旧代码与旧文档保持原样**（本文档集描述的是目标态）。

## 一、删除清单（第一个提交）

**代码**

- `backend/app/` 整目录（api/engine/games/agents/llm/storage/config/tui/export/scripts_helpers/main.py）
- `backend/tests/` 整目录（355 个旧测试随旧实现退役）
- `backend/scripts/`（run_match.py / e2e_real.py / export_dialog.py——功能由新 CLI 覆盖）

**依赖**（pyproject.toml）：删 `fastapi / uvicorn / sqlmodel / sqlalchemy / textual`；
保留 `aiosqlite / openai / pydantic` + dev 组。

**文档**（退役=删除，git 历史可回溯；新归属见对照表）

| 旧文档 | 处置 | 新归属 |
|---|---|---|
| `architecture.md` | 删除 | `backend/00-overview.md` + `01-structure.md` |
| `engine.md` | 删除 | `backend/02-flow.md` + `07-agent.md` |
| `game-plugin.md` | 删除 | `backend/02-flow.md`（无插件系统） |
| `events-storage.md` | 删除 | `backend/03-events.md` + `10-storage.md` |
| `agents-and-llm.md` | 删除 | `backend/06/07/08-prompts/agent/llm.md` |
| `configuration.md` | 删除 | `backend/09-config.md` |
| `api.md` | 删除 | 无 API（前端处置见下） |
| `milestones.md` | 删除 | `backend/13-testing.md` |
| `games/werewolf.md` | **收缩为纯规则书**（一~五节 + 九节；六~八节并入 06/03/04） | `backend/02/05-flow/rules.md` 引用之 |
| `frontend.md` | 顶部加状态注记「后端重写期间前端不可用」 | — |
| `roadmap.md` | 增「重建最小 API（支撑前端）」条目 | — |
| `CLAUDE.md` | 规则 5 删 boards、规则 6 换为指向 `backend/` 规格 | — |
| `README.md` | 文档地图改版（docs/backend/ 为后端唯一权威） | — |

**保留不动**：`frontend/` 全部代码、`backend/data/`（providers.json / personas.json / .env
原样可用）、`backend/.venv`、`docs/decisions.md`（append-only）、`docs/reviews/`（历史审查记录）。
旧 `whoisspy.db` 不迁移：改名留档（`whoisspy-legacy.db`）或直接删，新库从空开始。

## 二、落地提交序列（每步 TDD：先失败测试再实现）

| # | 提交 | 内容 | 依赖 |
|---|---|---|---|
| 1 | `chore(backend)!: 清空旧实现，保留配置与文档` | 上节删除清单 + 空的 `app/` `tests/` 骨架 + pyproject | — |
| 2 | `feat(backend): 事件与规则纯函数` | `events.py` `rules.py` + `test_events/test_rules` | 1 |
| 3 | `feat(backend): 状态 reducer` | `state.py` + 折叠一致性测试 | 2 |
| 4 | `feat(backend): 记忆与观赛投影` | `memory.py` `present.py` + 测试 | 2 |
| 5 | `feat(backend): prompt 拼装与 agent 协议` | `prompts.py` `agent.py` + 测试（网关用假 complete） | 2,3,4 |
| 6 | `feat(backend): LLM 网关（mock+真实+trace）` | `llm.py` + 测试 | 5 |
| 7 | `feat(backend): 存储` | `store.py` + 测试 | 2 |
| 8 | `feat(backend): 夜间流程` | `flow.py`（夜） + `test_flow_night` | 5,7 |
| 9 | `feat(backend): 白天与警长流程` | `flow.py`（昼） + `test_flow_day` | 8 |
| 10 | `feat(backend): 导出` | `export.py` + 测试 | 4,7 |
| 11 | `feat(backend): CLI 入口` | `main.py` `config.py` + `test_cli` | 全部 |
| 12 | `test(backend): e2e 确定性与验收基线` | `test_flow_e2e` 全绿 | 11 |

## 三、前端处置

- 代码**保留不动**（不做任何适配修改）；
- `frontend.md` 状态注记 + roadmap 记「重建最小 API」：将来恢复时**先写 API 规格**
  （REST/SSE 只做建局/事件回放/直播三件事），不复活旧 `api/app.py`；
- 在最小 API 重建前，前端构建（vitest/vue-tsc）允许保持绿但运行时无后端可连。

## 四、回滚

删除提交之后若要回滚：`git revert` 删除提交即可恢复旧实现与旧文档（decisions.md 追加
条目说明回滚原因）；`backend/data/` 未动，无数据损失。

## 五、执行记录（2026-09-25 落地偏差）

1. 文档规格提交（`fc2b4c3`）→ 清空提交（`1297133`）→ 12 步实现提交按序落地（`a13c188` … `7258d16`）。
2. **并发 emit 锁**：并行收票时多个 `ask` 交错调用 `emit`，`seq = len(events)+1` 分配与落库
   不原子 → 撞 `UNIQUE(match_id, seq)`。修复：`MatchRun._emit_lock` 内完成「分配 seq → INSERT
   → 归约」（`flow.emit`），保证单写者语义（10-storage 的「调用方分配 seq」以锁为前提）。
3. **channel.message 可见性**：频道发言必须标注 `vis=seat(狼队成员)`——`speak(channel=True)`
   增加 `vis` 参数，狼聊调用处传狼队成员集。
4. **被枪杀的警长必须处理徽章**：死亡链中「开枪打中警长」也要走移交/撕毁（规格 02-flow 已修正，
   原「target 存活」条件删除）。
5. **旧库防御**：`backend/data/whoisspy.db` 是 SQLModel 时代旧库（match 无 seed 列），
   `CREATE TABLE IF NOT EXISTS` 不重建已存在表 → `Store.init` 增加 `PRAGMA table_info` 检查，
   检测到旧库抛清晰错误（`test_store` 锁死）；本地旧库改名 `whoisspy-legacy.db` 留档。
6. **stdout 编码**：Windows 控制台默认 GBK，直播行（emoji/中文）需 `PYTHONIOENCODING=utf-8`
   或 `sys.stdout.reconfigure(encoding="utf-8")`——README 运行入口处注明。
7. 验收：后端 `203 passed`；e2e 确定性（同 seed 逐字节复现）、耗时 <5s、胜负双覆盖、护栏全绿；
   `--mock --seed 42` 冒烟完整跑通（81 次调用 / 0 兜底 / 好人胜 / 导出与 trace 正常）。
