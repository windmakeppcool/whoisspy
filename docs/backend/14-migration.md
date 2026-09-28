# 14 删除与落地顺序（migration）

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
