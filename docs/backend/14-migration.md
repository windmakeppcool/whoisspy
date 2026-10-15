# 14 删除与落地记录（migration）

> ✅ **已执行完成（2026-09-25）**：本文是后端推倒重写（D29）的**一次性落地记录**，
> 细节与提交序列见 git 历史；落地中发现的缺陷均已修复并固化进 `docs/backend/` 规格与测试。
> 此后仅作历史参考，不再更新（直播/建局去向见第三节）。

## 一、删除清单（第一个提交）

- **代码**：`backend/app/` 整目录（api/engine/games/agents/llm/storage/config/tui/export/
  scripts_helpers/main.py）、`backend/tests/`（355 个旧测试）、`backend/scripts/`；
- **依赖**：删 `fastapi / uvicorn / sqlmodel / sqlalchemy / textual`，保留 aiosqlite/openai/pydantic；
- **文档**：architecture/engine/game-plugin/events-storage/agents-and-llm/configuration/api/milestones
  删除，新归属见 [00-overview.md](00-overview.md) 六；games/werewolf.md 收缩为纯规则书；
- **保留不动**：`frontend/`、`backend/data/`（providers/personas/.env）、`docs/decisions.md`
  （append-only）；旧 whoisspy.db 改名留档（`whoisspy-legacy.db`）。

## 二、落地提交序列（12 步，每步 TDD）

清空提交 → 事件/规则纯函数 → reducer → 记忆/投影 → prompt/agent → 网关 → 存储 →
夜流程 → 昼流程与警长 → 导出 → CLI → e2e 确定性与验收基线。

## 三、前端处置（已被 PC 方案取代）

原「重建最小 API（REST/SSE）」方向已并入 PC 游戏方案（D34/D35，见
[../pc-game.md](../pc-game.md)）：前端代码仍保留不动，直播/建局改由 sidecar `--serve` +
WebSocket 帧接管（同一展示文档增量契约），**不复活旧 `api/app.py`**。

## 四、回滚

删除提交之后若要回滚：`git revert` 删除提交即可恢复旧实现与旧文档；`backend/data/` 未动，
无数据损失。

## 五、执行记录（关键偏差，均已修复并固化）

并发 emit 锁（seq 单写者原子分配）、channel.message 可见性（vis=狼队成员集）、枪杀警长
徽章处理、旧库 PRAGMA 防御、stdout UTF-8。验收：后端 203 passed；e2e 确定性（同 seed
逐字节复现）；`--mock --seed 42` 冒烟完整跑通（81 次调用 / 0 兜底 / 好人胜）。